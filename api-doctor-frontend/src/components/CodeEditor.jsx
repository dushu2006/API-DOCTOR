import React, { useEffect, useRef } from 'react';
import * as monaco from 'monaco-editor';
// monaco-editor 0.5x exposes workers through its exports map ("./*" -> esm/vs/*)
import editorWorker from 'monaco-editor/editor/editor.worker?worker';
import jsonWorker from 'monaco-editor/language/json/json.worker?worker';
import cssWorker from 'monaco-editor/language/css/css.worker?worker';
import htmlWorker from 'monaco-editor/language/html/html.worker?worker';
import tsWorker from 'monaco-editor/language/typescript/ts.worker?worker';

/* Real VS-Code-style editor (Monaco) with language-aware syntax highlighting. */

self.MonacoEnvironment = {
  getWorker(_workerId, label) {
    if (label === 'json') return new jsonWorker();
    if (label === 'css' || label === 'scss' || label === 'less') return new cssWorker();
    if (label === 'html' || label === 'handlebars' || label === 'razor') return new htmlWorker();
    if (label === 'typescript' || label === 'javascript') return new tsWorker();
    return new editorWorker();
  }
};

const THEME_NAME = 'api-doctor-dark';
let themeRegistered = false;

function registerTheme() {
  if (themeRegistered) return;
  monaco.editor.defineTheme(THEME_NAME, {
    base: 'vs-dark',
    inherit: true,
    // Dark+ inspired palette. Monaco emits language-specific token suffixes
    // (for example `keyword.python` and `type.identifier.ts`), so broad base
    // selectors are intentional: every supported file type receives useful
    // contrast instead of falling back to an all-white editor.
    rules: [
      { token: '', foreground: 'D4D4D4' },
      { token: 'comment', foreground: '6A9955', fontStyle: 'italic' },
      { token: 'keyword', foreground: 'C586C0' },
      { token: 'keyword.flow', foreground: 'C586C0' },
      { token: 'keyword.control', foreground: 'C586C0' },
      { token: 'operator', foreground: 'D4D4D4' },
      { token: 'string', foreground: 'CE9178' },
      { token: 'string.escape', foreground: 'D7BA7D' },
      { token: 'number', foreground: 'B5CEA8' },
      { token: 'constant', foreground: '4FC1FF' },
      { token: 'type', foreground: '4EC9B0' },
      { token: 'type.identifier', foreground: '4EC9B0' },
      { token: 'class', foreground: '4EC9B0' },
      { token: 'function', foreground: 'DCDCAA' },
      { token: 'function.call', foreground: 'DCDCAA' },
      { token: 'identifier.function', foreground: 'DCDCAA' },
      { token: 'variable', foreground: '9CDCFE' },
      { token: 'variable.predefined', foreground: '4FC1FF' },
      { token: 'tag', foreground: '569CD6' },
      { token: 'metatag', foreground: '569CD6' },
      { token: 'attribute.name', foreground: '9CDCFE' },
      { token: 'attribute.value', foreground: 'CE9178' },
      { token: 'delimiter', foreground: '808080' },
      { token: 'delimiter.bracket', foreground: 'FFD700' },
      { token: 'regexp', foreground: 'D16969' }
    ],
    colors: {
      'editor.background': '#070809',
      'editor.foreground': '#E2E3E8',
      'editor.lineHighlightBackground': '#101114',
      'editorLineNumber.foreground': '#44474D',
      'editorLineNumber.activeForeground': '#9188FF',
      'editor.selectionBackground': '#332F5C',
      'editorCursor.foreground': '#9188FF',
      'editorIndentGuide.background': '#24262A',
      'scrollbarSlider.background': '#292B3088',
      'scrollbarSlider.hoverBackground': '#45485088',
      'diffEditor.insertedTextBackground': '#10B98122',
      'diffEditor.removedTextBackground': '#F43F5E22',
      'diffEditor.insertedLineBackground': '#10B98118',
      'diffEditor.removedLineBackground': '#F43F5E18'
    }
  });
  themeRegistered = true;
}

const LANGUAGE_BY_EXT = {
  py: 'python', pyi: 'python',
  js: 'javascript', mjs: 'javascript', cjs: 'javascript', jsx: 'javascript',
  ts: 'typescript', tsx: 'typescript',
  html: 'html', htm: 'html', vue: 'html', svelte: 'html',
  css: 'css', scss: 'scss', less: 'less',
  json: 'json', jsonc: 'json',
  md: 'markdown', markdown: 'markdown',
  yml: 'yaml', yaml: 'yaml',
  xml: 'xml', svg: 'xml',
  sql: 'sql', graphql: 'graphql', gql: 'graphql',
  sh: 'shell', bash: 'shell', zsh: 'shell', fish: 'shell',
  toml: 'ini', ini: 'ini', cfg: 'ini', conf: 'ini', env: 'ini', properties: 'ini',
  dockerfile: 'dockerfile',
  java: 'java', go: 'go', rs: 'rust', rb: 'ruby', php: 'php', swift: 'swift', kt: 'kotlin',
  c: 'c', h: 'c', cpp: 'cpp', cc: 'cpp', cxx: 'cpp', hpp: 'cpp', cs: 'csharp'
};

const LANGUAGE_BY_NAME = {
  dockerfile: 'dockerfile',
  makefile: 'makefile',
  'package.json': 'json',
  'package-lock.json': 'json',
  'tsconfig.json': 'json',
  'jsconfig.json': 'json',
  'requirements.txt': 'plaintext',
  '.env': 'ini',
  '.env.example': 'ini',
  '.gitignore': 'plaintext',
};

function languageForPath(path = '') {
  const name = path.split('/').pop() || '';
  const lowerName = name.toLowerCase();
  if (LANGUAGE_BY_NAME[lowerName]) return LANGUAGE_BY_NAME[lowerName];
  if (lowerName.startsWith('.env.')) return 'ini';
  const ext = (name.includes('.') ? name.split('.').pop() : '').toLowerCase();
  return LANGUAGE_BY_EXT[ext] || 'plaintext';
}

function createModel(value, language, uri) {
  const existing = uri ? monaco.editor.getModel(monaco.Uri.parse(uri)) : null;
  if (existing) {
    existing.setValue(value || '');
    monaco.editor.setModelLanguage(existing, language);
    return existing;
  }
  return monaco.editor.createModel(value || '', language, uri ? monaco.Uri.parse(uri) : undefined);
}

export default function CodeEditor({
  mode = 'view',          // 'view' | 'diff'
  value = '',
  original = '',
  modified = '',
  path = '',
  modifiedPath = '',
  highlightLine = null,
  readOnly = true
}) {
  const containerRef = useRef(null);
  const editorRef = useRef(null);
  const decorationsRef = useRef(null);
  const modeRef = useRef(null);

  // Create / recreate the editor when the mode changes.
  useEffect(() => {
    registerTheme();
    const container = containerRef.current;
    if (!container) return undefined;

    if (editorRef.current) {
      editorRef.current.dispose();
      editorRef.current = null;
      decorationsRef.current = null;
    }

    if (mode === 'diff') {
      const diffEditor = monaco.editor.createDiffEditor(container, {
        theme: THEME_NAME,
        readOnly: true,
        // The editor is a read-only review surface. Disabling Monaco's context
        // menu also avoids a Monaco disposal race when React switches between
        // the normal and split editor while a menu debounce is pending.
        contextmenu: false,
        renderSideBySide: true,
        automaticLayout: false,
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 12,
        lineHeight: 20,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        renderWhitespace: 'boundary',
        ignoreTrimWhitespace: false
      });
      editorRef.current = diffEditor;
      modeRef.current = 'diff';
    } else {
      const editor = monaco.editor.create(container, {
        theme: THEME_NAME,
        value: value || '',
        language: languageForPath(path),
        readOnly,
        // This panel does not support source editing, so a context menu only
        // introduces lifecycle work during rapid view switches.
        contextmenu: false,
        automaticLayout: false,
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 12,
        lineHeight: 20,
        minimap: { enabled: true, scale: 1 },
        scrollBeyondLastLine: false,
        renderWhitespace: 'boundary',
        smoothScrolling: true,
        cursorBlinking: 'smooth',
        padding: { top: 10 }
      });
      editorRef.current = editor;
      modeRef.current = 'view';
    }

    const observer = new ResizeObserver(() => {
      editorRef.current?.layout();
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      if (editorRef.current) {
        editorRef.current.dispose();
        editorRef.current = null;
        decorationsRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  // Keep view-mode content/language in sync.
  useEffect(() => {
    if (mode !== 'view' || !editorRef.current || modeRef.current !== 'view') return;
    const editor = editorRef.current;
    const language = languageForPath(path);
    const model = createModel(value, language, path ? `inmemory://doctor/${path}` : undefined);
    if (editor.getModel() !== model) editor.setModel(model);
  }, [mode, value, path]);

  // Keep diff-mode models in sync.
  useEffect(() => {
    if (mode !== 'diff' || !editorRef.current || modeRef.current !== 'diff') return;
    const language = languageForPath(modifiedPath || path);
    const originalModel = createModel(original, language, 'inmemory://doctor/diff-original');
    const modifiedModel = createModel(modified, language, 'inmemory://doctor/diff-modified');
    editorRef.current.setModel({ original: originalModel, modified: modifiedModel });
  }, [mode, original, modified, path, modifiedPath]);

  // Failure-line decoration + auto reveal.
  useEffect(() => {
    if (mode !== 'view' || !editorRef.current || modeRef.current !== 'view') return;
    const editor = editorRef.current;
    const lineCount = editor.getModel()?.getLineCount() || 0;
    if (highlightLine && highlightLine >= 1 && highlightLine <= lineCount) {
      decorationsRef.current = editor.createDecorationsCollection([
        {
          range: new monaco.Range(highlightLine, 1, highlightLine, 1),
          options: {
            isWholeLine: true,
            className: 'doctor-failure-line',
            glyphMarginClassName: 'doctor-failure-glyph'
          }
        }
      ]);
      editor.revealLineInCenterIfOutsideViewport(highlightLine);
    } else if (decorationsRef.current) {
      decorationsRef.current.clear();
      decorationsRef.current = null;
    }
  }, [mode, highlightLine, value, path]);

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} />;
}
