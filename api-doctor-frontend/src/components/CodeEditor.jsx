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
    rules: [
      { token: 'comment', foreground: '5C6B7F', fontStyle: 'italic' },
      { token: 'keyword', foreground: 'F0A93A' },
      { token: 'keyword.flow', foreground: 'F0A93A' },
      { token: 'string', foreground: '7EE787' },
      { token: 'string.escape', foreground: '34D399' },
      { token: 'number', foreground: '79C0FF' },
      { token: 'constant', foreground: '79C0FF' },
      { token: 'type', foreground: '38BDF8' },
      { token: 'class', foreground: '38BDF8' },
      { token: 'function', foreground: 'D2A8FF' },
      { token: 'variable', foreground: 'E8ECF1' },
      { token: 'tag', foreground: 'F0A93A' },
      { token: 'attribute.name', foreground: '38BDF8' },
      { token: 'attribute.value', foreground: '7EE787' },
      { token: 'delimiter', foreground: '8292A6' },
      { token: 'regexp', foreground: 'F87171' }
    ],
    colors: {
      'editor.background': '#0A0E14',
      'editor.foreground': '#E8ECF1',
      'editor.lineHighlightBackground': '#131A24',
      'editorLineNumber.foreground': '#4C5B6E',
      'editorLineNumber.activeForeground': '#F0A93A',
      'editor.selectionBackground': '#243144',
      'editorCursor.foreground': '#F0A93A',
      'editorIndentGuide.background': '#1E2B3C',
      'scrollbarSlider.background': '#1E2B3C88',
      'scrollbarSlider.hoverBackground': '#2E405988',
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
  html: 'html', htm: 'html',
  css: 'css', scss: 'scss', less: 'less',
  json: 'json', jsonc: 'json',
  md: 'markdown', markdown: 'markdown',
  yml: 'yaml', yaml: 'yaml',
  xml: 'xml', svg: 'xml',
  sql: 'sql',
  sh: 'shell', bash: 'shell', zsh: 'shell',
  toml: 'ini', ini: 'ini', cfg: 'ini',
  dockerfile: 'dockerfile',
  java: 'java', go: 'go', rs: 'rust', rb: 'ruby', php: 'php',
  c: 'c', h: 'c', cpp: 'cpp', hpp: 'cpp'
};

export function languageForPath(path = '') {
  const name = path.split('/').pop() || '';
  if (/^dockerfile$/i.test(name)) return 'dockerfile';
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
