import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import {
  collectPythonMessages,
  compareCatalogs,
  sortedCatalog
} from './generate-i18n-catalog.mjs';

function tempPythonSource(content, { filename = 'module.py', nested = null } = {}) {
  const root = mkdtempSync(join(tmpdir(), 'i18n-catalog-test-'));
  if (nested) mkdirSync(join(root, nested), { recursive: true });
  writeFileSync(join(root, ...(nested ? [nested, filename] : [filename])), content);
  return { root, cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

function emptyReport() {
  return {
    missingSourceKeys: [],
    missingEnglishKeys: [],
    staleSourceKeys: [],
    staleEnglishKeys: [],
    mismatchedChineseValues: [],
    untranslatedEnglishValues: [],
    mismatchedPlaceholders: []
  };
}

test('v0.1.2 CI regression: CJK strings added to Python sources fail an unsynced catalog', () => {
  // The v0.1.2 run failed because duplicate-detection and categorization modules
  // introduced new CJK strings (category tags, regexes, docstrings) that were
  // missing from zh-CN.json/en-US.json, producing missingSourceKeys.
  const { root, cleanup } = tempPythonSource(
    'CATEGORY_TAG = "中学教材-化学"\nEDITION_RE = r"第\\s*[一二三四五六七八九十百\\d]{0,3}\\s*版"\n'
  );
  const catalog = sortedCatalog([...collectPythonMessages(root)]);
  const report = compareCatalogs(catalog, {}, {});
  assert.deepEqual(report.missingSourceKeys, ['第\\s*[一二三四五六七八九十百\\d]{0,3}\\s*版', '中学教材-化学']);
  assert.deepEqual(report.missingEnglishKeys, report.missingSourceKeys);
  cleanup();
});

test('a fully synchronized catalog passes with an empty report', () => {
  const { root, cleanup } = tempPythonSource(
    'TAG = "历史"\nEDITION_RE = r"第\\s*[一二三四五六七八九十百\\d]{0,3}\\s*版"\n'
  );
  const catalog = sortedCatalog([...collectPythonMessages(root)]);
  const zh = { ...catalog };
  const en = {
    '历史': 'History',
    '第\\s*[一二三四五六七八九十百\\d]{0,3}\\s*版': 'Edition marker regex (e.g. a Chinese "2nd edition" suffix)'
  };
  assert.deepEqual(compareCatalogs(catalog, zh, en), emptyReport());
  cleanup();
});

test('an English translation that still contains CJK is reported as untranslated', () => {
  const { root, cleanup } = tempPythonSource('TAGLINE = "存你所藏，随时可读"\n');
  const catalog = sortedCatalog([...collectPythonMessages(root)]);
  const zh = { '存你所藏，随时可读': '存你所藏，随时可读' };
  const en = { '存你所藏，随时可读': '存你所藏，随时可读' }; // forgot to translate
  const report = compareCatalogs(catalog, zh, en);
  assert.deepEqual(report.untranslatedEnglishValues, [['存你所藏，随时可读', '存你所藏，随时可读']]);
  cleanup();
});

test('stale keys left in the Chinese catalog are reported', () => {
  const { root, cleanup } = tempPythonSource('TAG = "历史"\n');
  const catalog = sortedCatalog([...collectPythonMessages(root)]);
  const zh = { '历史': '历史', '已删除文案': '已删除文案' };
  const en = { '历史': 'History' };
  const report = compareCatalogs(catalog, zh, en);
  assert.deepEqual(report.staleSourceKeys, ['已删除文案']);
  assert.deepEqual(report.staleEnglishKeys, []);
  cleanup();
});

test('Chinese catalog values must equal their keys', () => {
  const { root, cleanup } = tempPythonSource('TAG = "历史"\n');
  const catalog = sortedCatalog([...collectPythonMessages(root)]);
  const zh = { '历史': '错别字' };
  const en = { '历史': 'History' };
  assert.equal(compareCatalogs(catalog, zh, en).mismatchedChineseValues.length, 1);
  cleanup();
});

test('translated placeholders must keep the source interpolation slots', () => {
  const { root, cleanup } = tempPythonSource('SUMMARY = f"共{count}本图书"\n');
  const catalog = sortedCatalog([...collectPythonMessages(root)]);
  const zh = { '共{value0}本图书': '共{value0}本图书' };
  const en = { '共{value0}本图书': 'Total books' }; // dropped {value0}
  const report = compareCatalogs(catalog, zh, en);
  assert.equal(report.mismatchedPlaceholders.length, 1);
  assert.deepEqual(report.mismatchedPlaceholders[0].translatedPlaceholders, []);
  cleanup();
});

test('CJK collection covers literals, docstrings, regexes, and f-strings; skips tests/__pycache__', () => {
  const root = mkdtempSync(join(tmpdir(), 'i18n-catalog-test-'));
  writeFileSync(
    join(root, 'module.py'),
    [
      '"""模块级中文文档说明。"""',
      'TITLE = "哈利波特"',
      'EDITION_RE = r"第\\d+版"',
      'FRIENDLY = f"书名为{TITLE}"',
      'PLAIN = "pure ascii only"',
      ''
    ].join('\n')
  );
  mkdirSync(join(root, 'tests'));
  writeFileSync(join(root, 'tests', 'unit.py'), 'X = "测试用例"\n');
  mkdirSync(join(root, '__pycache__'));
  writeFileSync(join(root, '__pycache__', 'cache.py'), 'Y = "缓存文件"\n');

  const messages = collectPythonMessages(root);
  assert.ok(messages.has('模块级中文文档说明。'));
  assert.ok(messages.has('哈利波特'));
  assert.ok(messages.has('第\\d+版'));
  assert.ok(messages.has('书名为{value0}'));
  assert.ok(!messages.has('pure ascii only'));
  assert.ok(!messages.has('测试用例'));
  assert.ok(!messages.has('缓存文件'));
  rmSync(root, { recursive: true, force: true });
});

test('catalog keys are sorted with zh-CN pinyin collation and blanks are dropped', () => {
  const sorted = sortedCatalog(new Set(['历史', '   ', '一隅书架', '化学']));
  // zh-CN collation sorts by pinyin: hua(化) < li(历) < yi(一)
  assert.deepEqual(Object.keys(sorted), ['化学', '历史', '一隅书架']);
  assert.equal(Object.values(sorted).every((value, index) => Object.keys(sorted)[index] === value), true);
});
