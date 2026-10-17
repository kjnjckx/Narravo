"""Offline EPUB and PDF parsers. Executed by resource-limited worker processes."""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from typing import Any
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from lxml import etree  # type: ignore[import-untyped]
from pypdf import PdfReader

from .archive import inspect_zip, read_entry, safe_name
from .domain import DomainError, require

MAX_TEXT = 8 * 1024**2


def xml(raw: bytes) -> Any:
    require(
        b"<!ENTITY" not in raw.upper(),
        "UNSAFE_XML",
        "电子书包含外部实体或文档类型声明，请先转换为普通 EPUB。",
    )
    root = etree.fromstring(
        raw,
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            load_dtd=False,
            huge_tree=False,
        ),
    )
    require(
        not any(isinstance(element, etree._Entity) for element in root.iter()),
        "UNSAFE_XML",
        "EPUB 包含不受支持的实体引用。",
    )
    return root


def resource(base: str, href: str) -> str:
    url = urlsplit(unquote(href))
    require(
        not url.scheme and not url.netloc and not url.path.startswith("/"),
        "UNSAFE_EPUB",
        "EPUB 正文或目录引用了外部资源，已停止导入。",
    )
    path = posixpath.normpath(posixpath.join(posixpath.dirname(base), url.path))
    require(safe_name(path), "UNSAFE_EPUB", "EPUB 资源超出了电子书目录。")
    return path


def epub(raw: bytes) -> dict[str, Any]:
    warnings = ["仅导入纯文本；图片、样式、音视频及特殊排版不会保留。"]
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = inspect_zip(archive)
            require(
                "META-INF/encryption.xml" not in entries,
                "DRM_UNSUPPORTED",
                "此 EPUB 含加密资源，暂不支持；请选择无 DRM 的版本。",
            )
            container = xml(read_entry(archive, "META-INF/container.xml"))
            roots = container.xpath("//*[local-name()='rootfile']/@full-path")
            require(bool(roots) and safe_name(roots[0]), "INVALID_EPUB", "找不到 EPUB 内容清单。")
            package_path = roots[0]
            package = xml(read_entry(archive, package_path))
            require(
                not package.xpath(
                    "//*[local-name()='meta'][normalize-space(text())='pre-paginated']"
                ),
                "FIXED_LAYOUT_UNSUPPORTED",
                "暂不支持固定版式 EPUB，请转换为流式排版版本。",
            )
            items = {
                item.get("id"): item
                for item in package.xpath("//*[local-name()='manifest']/*[local-name()='item']")
            }
            metadata = {
                key: package.xpath(
                    f"string(//*[local-name()='metadata']/*[local-name()='{key}'][1])"
                )
                for key in ("title", "creator")
            }
            cover_ids = package.xpath("//*[local-name()='meta'][@name='cover']/@content")
            for item in items.values():
                if (
                    "cover-image" in item.get("properties", "").split()
                    or item.get("id") in cover_ids
                ):
                    cover_path = resource(package_path, item.get("href", ""))
                    if cover_path in entries:
                        metadata["cover_resource"] = cover_path
                if item.get("media-overlay"):
                    warnings.append("电子书媒体覆盖不会导入；朗读使用已保存的纯文本。")
            titles: dict[str, str] = {}
            # EPUB 3 nav and EPUB 2 NCX are hints; spine remains authoritative.
            for item in items.values():
                media = item.get("media-type", "")
                if (
                    "nav" not in item.get("properties", "").split()
                    and media != "application/x-dtbncx+xml"
                ):
                    continue
                nav_path = resource(package_path, item.get("href", ""))
                nav = xml(read_entry(archive, nav_path))
                if media == "application/x-dtbncx+xml":
                    for point in nav.xpath("//*[local-name()='navPoint']"):
                        href = point.xpath("./*[local-name()='content']/@src")
                        label = point.xpath(
                            "string(./*[local-name()='navLabel']/*[local-name()='text'])"
                        )
                        if href:
                            titles.setdefault(resource(nav_path, href[0]), label.strip())
                else:
                    for anchor in nav.xpath("//*[local-name()='nav']//*[local-name()='a'][@href]"):
                        href = anchor.get("href")
                        if href and not urlsplit(href).scheme:
                            titles.setdefault(
                                resource(nav_path, href), "".join(anchor.itertext()).strip()
                            )
            sections: list[dict[str, Any]] = []
            text_size = 0
            for ref in package.xpath("//*[local-name()='spine']/*[local-name()='itemref']"):
                if ref.get("linear") == "no":
                    continue
                item = items.get(ref.get("idref"))
                require(item is not None, "INVALID_EPUB", "EPUB 阅读顺序含缺失的资源。")
                assert item is not None
                path = resource(package_path, item.get("href", ""))
                require(
                    item.get("media-type") in {"application/xhtml+xml", "text/html"},
                    "UNSUPPORTED_EPUB",
                    "EPUB 阅读顺序中有不支持的正文类型。",
                )
                data = read_entry(archive, path)
                # Parse XML once for entity rejection and stable element source locators.
                root = xml(data)
                headings = root.xpath("//*[local-name()='h1' or local-name()='h2']")
                heading = "".join(headings[0].itertext()).strip() if headings else ""
                soup = BeautifulSoup(data, "lxml")
                for unwanted in soup(
                    ["script", "style", "iframe", "object", "embed", "svg", "nav", "noscript"]
                ):
                    unwanted.decompose()
                body = soup.body or soup
                for br in body.find_all("br"):
                    br.replace_with("\n")
                for block in body.find_all(
                    ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "div"]
                ):
                    block.insert_before("\n\n")
                    block.insert_after("\n\n")
                text = re.sub(r"\n[ \t]*\n+", "\n\n", body.get_text("", strip=False))
                text = text.replace("\r\n", "\n").strip()
                if not text:
                    warnings.append(f"已跳过无可提取文本的资源：{path}")
                    continue
                text_size += len(text.encode("utf-8"))
                require(text_size <= MAX_TEXT, "TEXT_LIMIT", "提取正文超过 8 MiB，请拆分电子书。")
                sections.append(
                    {
                        "title": (titles.get(path) or heading or f"第 {len(sections) + 1} 节")[
                            :120
                        ],
                        "text": text,
                        "source_locator": {"resource": path, "element": "body"},
                    }
                )
            require(bool(sections), "EMPTY_DOCUMENT", "EPUB 没有可导入的文本正文。")
            return {
                "sections": sections,
                "warnings": warnings,
                "encoding": "epub",
                "metadata": metadata,
                "omitted_pages": [],
            }
    except (KeyError, zipfile.BadZipFile, etree.XMLSyntaxError, ValueError) as exc:
        raise DomainError("INVALID_EPUB", "EPUB 结构或资源损坏，请换用其他版本。") from exc


def pdf_reader(raw: bytes, password: str) -> PdfReader:
    try:
        reader = PdfReader(io.BytesIO(raw), strict=False)
        if reader.is_encrypted:
            require(
                bool(password), "PDF_PASSWORD_REQUIRED", "PDF 已加密，请填写密码后重新选择文件。"
            )
            require(
                bool(reader.decrypt(password)),
                "PDF_PASSWORD_INVALID",
                "PDF 密码不正确，请重新输入。",
            )
        return reader
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError(
            "INVALID_PDF", "无法读取 PDF，请检查文件是否完整或换用其他版本。"
        ) from exc


def pdf_count(raw: bytes, password: str) -> dict[str, Any]:
    reader = pdf_reader(raw, password)
    total = len(reader.pages)
    require(0 < total <= 2000, "PDF_PAGE_LIMIT", "PDF 页数必须在 1–2000 页之间。")
    return {"pages": total}


def pdf_page(raw: bytes, password: str, page: int) -> dict[str, Any]:
    reader = pdf_reader(raw, password)
    try:
        current = reader.pages[page]
        content = current.get_contents()
        require(
            content is None or len(content.get_data()) <= 10 * 1024**2,
            "PDF_PAGE_LIMIT",
            "此页内容流过大，已跳过。",
        )
        text = (current.extract_text() or "").replace("\r\n", "\n").strip()
        require(
            len(text.encode("utf-8")) <= 1024**2, "PDF_PAGE_LIMIT", "此页提取文本过大，已跳过。"
        )
        # Conservative repair only: CJK soft line wraps and English hyphen wraps.
        text = re.sub(r"([\u3400-\u9fff])\n(?=[\u3400-\u9fff])", r"\1", text)
        text = re.sub(r"([A-Za-z])-\n(?=[a-z])", r"\1", text)
        quality = sum(ch.isprintable() and not ch.isspace() for ch in text)
        require(
            quality > 0 and text.count("\ufffd") <= max(1, len(text) // 20),
            "OCR_REQUIRED",
            "此页没有可靠文本，需要 OCR。",
        )
        return {"title": f"第 {page + 1} 页", "text": text, "source_locator": {"page": page + 1}}
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError("PDF_PAGE_FAILED", "此页解析失败，已跳过。") from exc
