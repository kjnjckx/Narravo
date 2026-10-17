import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { compile } from 'json-schema-to-typescript';
import { root, python, env } from './engine-env.mjs';
const processResult = spawnSync(python, [resolve(root, 'scripts/export-contracts.py')], {
  env,
  encoding: 'utf8',
});
if (processResult.status !== 0) throw new Error(processResult.stderr);
const { schema, methods } = JSON.parse(processResult.stdout);
const types = await compile(schema, 'Contracts', {
  bannerComment: '/* Generated from Python contracts. Do not edit. */',
  additionalProperties: false,
  ignoreMinAndMaxItems: true,
});
const methodMap =
  '\nexport interface RpcMethods {\n' +
  Object.entries(methods)
    .map(([method, [params, result]]) => `  '${method}': { params: ${params}; result: ${result} };`)
    .join('\n') +
  '\n}\n';
const require = createRequire(resolve(root, 'apps/desktop/package.json'));
const Ajv = require('ajv');
const standalone = require('ajv/dist/standalone').default;
const ajv = new Ajv({ strict: false, code: { source: true, esm: true } });
ajv.addSchema(schema, 'narravo');
const resultNames = [...new Set(Object.values(methods).map((pair) => pair[1]))];
const references = Object.fromEntries(resultNames.map((name) => [name, `narravo#/$defs/${name}`]));
let validators = standalone(ajv, references);
// Emit a self-contained Unicode helper rather than CommonJS imports in renderer code.
validators = validators.replaceAll(
  'require("ajv/dist/runtime/ucs2length").default',
  '(text => Array.from(text).length)',
);
if (validators.includes('require('))
  throw new Error('Unexpected runtime dependency in standalone validator');
const declarations =
  resultNames
    .map((name) => `export declare const ${name}: (data: unknown) => boolean;`)
    .join('\n') + '\n';
const files = {
  'packages/contracts/validators.js':
    '// Generated static validators. No runtime code generation.\n' + validators + '\n',
  'packages/contracts/validators.d.ts': declarations,
  'packages/contracts/schema.json': JSON.stringify(schema, null, 2) + '\n',
  'packages/contracts/index.ts': types + methodMap,
  'packages/contracts/methods.json': JSON.stringify(methods, null, 2) + '\n',
};
for (const [file, content] of Object.entries(files)) {
  const target = resolve(root, file);
  if (process.argv.includes('--check')) {
    if (readFileSync(target, 'utf8') !== content) throw new Error(`Contract drift: ${file}`);
  } else writeFileSync(target, content);
}
console.log(
  process.argv.includes('--check') ? 'Contracts are synchronized.' : 'Contracts generated.',
);
