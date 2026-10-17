import { describe, it, expect } from 'vitest';
import { toCodePoint, wordCount } from './store';
import { unwrap } from './rpc';
describe('Unicode boundary and RPC contract', () => {
  it('counts non-whitespace code points, not UTF-16 units', () => {
    expect(wordCount('林舟 😀\n𠮷 e\u0301')).toBe(6);
    expect(toCodePoint('甲😀乙', 3)).toBe(2);
  });
  it('rejects schema versions and malformed engine results', () => {
    expect(() =>
      unwrap('book.list', { jsonrpc: '2.0', schema_version: 2, id: '1', result: { books: [] } }),
    ).toThrow();
    expect(() =>
      unwrap('book.list', {
        jsonrpc: '2.0',
        schema_version: 1,
        id: '1',
        result: { books: [{ title: 'invalid' }] },
      }),
    ).toThrow();
    expect(
      unwrap('book.list', { jsonrpc: '2.0', schema_version: 1, id: '1', result: { books: [] } }),
    ).toEqual({ books: [] });
  });
});
