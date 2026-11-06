// Execute the shared preference layer with fresh, saved and malformed preferences.
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
function load(saved) {
  const context = {Intl, Map, Set, CustomEvent: class {},
    navigator: {languages: ['zh-CN'], language: 'zh-CN'},
    localStorage: {getItem: () => saved, setItem() {}},
    matchMedia: () => ({matches: false, addEventListener() {}}),
    document: {documentElement: {dataset: {}}, dispatchEvent() {}, addEventListener() {}}};
  context.window = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(require('path').join(__dirname, '../../cecropis/web/static/js/ui_preferences.js'), 'utf8'), context);
  return context;
}
for (const saved of [null, '{broken', '{}', 'null', '{"language":"unsupported"}']) {
  const context = load(saved);
  assert.equal(context.UI.preferences.language, 'en');
  assert.equal(context.document.documentElement.lang, 'en');
}
for (const language of ['en', 'zh-CN', 'ja', 'fr', 'de', 'es']) {
  const context = load(JSON.stringify({language, theme: 'dark'}));
  assert.equal(context.UI.preferences.language, language);
  assert.equal(context.UI.preferences.theme, 'dark');
}
console.log('Default English and six saved language preferences: passed');
