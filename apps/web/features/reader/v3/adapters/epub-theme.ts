import type { ReaderPreferences } from '@booknook/reader-core';
import { readerThemeSurfaces } from '../../reader-theme';
import { fallbackEpubFont, type EpubFontResolution } from './epub-font';

const COMPACT_EPUB_VIEWPORT_MAX_WIDTH = 640;

export type EpubViewportLayout = Readonly<{
  compact: boolean;
  automaticColumnCount: 1 | 2;
  inlinePadding: string;
  paginatorGap: string;
  bottomInset: string;
}>;

const DEFAULT_EPUB_VIEWPORT_LAYOUT: EpubViewportLayout = Object.freeze({
  compact: false,
  automaticColumnCount: 2,
  inlinePadding: '24px',
  paginatorGap: '7%',
  bottomInset: '0px'
});

export function resolveEpubViewportLayout(viewportWidth: number): EpubViewportLayout {
  const compact = Number.isFinite(viewportWidth)
    && viewportWidth > 0
    && viewportWidth <= COMPACT_EPUB_VIEWPORT_MAX_WIDTH;
  return compact
    ? {
        compact: true,
        automaticColumnCount: 1,
        inlinePadding: '1em',
        paginatorGap: '0%',
        bottomInset: 'calc(var(--booknook-safe-area-bottom) + 10px)'
      }
    : {
        ...DEFAULT_EPUB_VIEWPORT_LAYOUT,
        automaticColumnCount: viewportWidth >= 1000 ? 2 : 1
      };
}

export function epubSurfaceColor(preferences: ReaderPreferences) {
  return readerThemeSurfaces[preferences.appearance.theme].background;
}

export function epubSurfaceTextColor(preferences: ReaderPreferences) {
  return readerThemeSurfaces[preferences.appearance.theme].color;
}

export function epubPageWidth(preferences: ReaderPreferences) {
  return Math.max(600, Math.min(1350, Math.round(preferences.epub.pageWidth)));
}

function epubVerticalSpacing(preferences: ReaderPreferences) {
  return preferences.epub.flow === 'paginated'
    ? 'clamp(32px, 5vh, 64px)'
    : 'clamp(28px, 4vh, 56px)';
}

function epubMobileTopSpacing(preferences: ReaderPreferences) {
  return preferences.epub.flow === 'paginated'
    ? 'clamp(16px, 2.5vh, 32px)'
    : 'clamp(14px, 2vh, 28px)';
}

export function createEpubThemeSnapshot(
  preferences: ReaderPreferences,
  resolvedFont = fallbackEpubFont(preferences.epub.fontFamily),
  viewportLayout: EpubViewportLayout = DEFAULT_EPUB_VIEWPORT_LAYOUT
) {
  const tokens = readerThemeSurfaces[preferences.appearance.theme];
  const maxWidth = epubPageWidth(preferences);
  const fontSize = Math.max(14, Math.min(30, Math.round(preferences.epub.fontSize)));
  const lineHeight = Math.max(1.4, Math.min(2.4, preferences.epub.lineHeight));
  const fontWeight = preferences.epub.fontWeight;
  const letterSpacing = preferences.epub.letterSpacing;
  const pagePadding = viewportLayout.compact
    ? { narrow: '0.5em', standard: '1em', wide: '1.5em' }[preferences.epub.pageMargin]
    : { narrow: '16px', standard: '24px', wide: '40px' }[preferences.epub.pageMargin];
  const paragraphIndent = Math.max(0, Math.min(4, preferences.epub.typography.paragraphIndent));
  const paragraphSpacing = Math.max(0, Math.min(1.5, preferences.epub.typography.paragraphSpacing));
  const paragraphAlignment = preferences.epub.typography.textAlign === 'publisher'
    ? ''
    : `text-align: ${preferences.epub.typography.textAlign} !important;`;
  const paragraphSpacingRule = paragraphSpacing === 0
    ? ''
    : `
      margin-block-start: var(--booknook-reader-paragraph-spacing) !important;
      margin-block-end: var(--booknook-reader-paragraph-spacing) !important;
    `;
  const verticalSpacing = epubVerticalSpacing(preferences);
  const fontFace = resolvedFont.embedded
    ? `@font-face { font-family: "${resolvedFont.embedded.family}"; src: url("${resolvedFont.embedded.url}") format("woff2"); font-display: swap; font-style: normal; font-weight: 400; }`
    : '';
  const hiddenScrollbar = preferences.epub.flow === 'scrolled'
    ? `
      html, body { scrollbar-width: none !important; -ms-overflow-style: none !important; }
      html::-webkit-scrollbar, body::-webkit-scrollbar { display: none !important; width: 0 !important; height: 0 !important; }
    `
    : '';
  // :is() adopts the strongest branch specificity while the universal branch
  // matches. This lets one late snapshot beat hostile author !important rules
  // without walking and rewriting the whole document on every theme change.
  const protectedBody = 'body:is(#booknook-theme-guard#booknook-theme-guard#booknook-theme-guard, *)';
  const fontOverride = preferences.epub.typography.allowPublisherFonts
    ? ''
    : `${protectedBody}, ${protectedBody} * { font-family: var(--booknook-reader-font-family) !important; }`;
  const lineHeightOverride = preferences.epub.typography.preservePublisherStyles
    ? ''
    : `${protectedBody} * { line-height: inherit !important; }`;
  const colorOverride = preferences.epub.typography.allowPublisherColors
    ? ''
    : `
      ${protectedBody} * { background-color: transparent !important; color: inherit !important; }
      ${protectedBody} > div, ${protectedBody} > section, ${protectedBody} > article, ${protectedBody} > main,
      ${protectedBody} .calibre, ${protectedBody} .chapter, ${protectedBody} .section,
      ${protectedBody} [style*="background"], ${protectedBody} [bgcolor] {
        background: transparent !important;
        background-color: transparent !important;
        color: inherit !important;
      }
    `;

  return `
    ${fontFace}
    ${hiddenScrollbar}
    :root {
      color-scheme: ${tokens.colorScheme} !important;
      /* Foliate uses this public variable to repaint the paginator background
         that surrounds the current iframe without waiting for a page turn. */
      --theme-bg-color: ${tokens.background};
      --booknook-reader-background: ${tokens.background};
      --booknook-reader-color: ${tokens.color};
      --booknook-reader-link: ${tokens.link};
      --booknook-reader-font-size: ${fontSize}px;
      --booknook-reader-line-height: ${lineHeight};
      --booknook-reader-paragraph-indent: ${paragraphIndent}em;
      --booknook-reader-paragraph-spacing: ${paragraphSpacing}em;
      --booknook-reader-page-width: ${maxWidth}px;
      --booknook-reader-font-family: ${resolvedFont.stack};
      --booknook-reader-font-weight: ${fontWeight};
      --booknook-reader-letter-spacing: ${letterSpacing}em;
      --booknook-reader-padding-inline: ${pagePadding};
      --booknook-reader-padding-top: ${viewportLayout.compact ? epubMobileTopSpacing(preferences) : verticalSpacing};
      --booknook-reader-padding-bottom: ${verticalSpacing};
    }
    html, ${protectedBody} {
      background: var(--booknook-reader-background) !important;
      color: var(--booknook-reader-color) !important;
    }
    html {
      font-size: var(--booknook-reader-font-size) !important;
      font-weight: var(--booknook-reader-font-weight) !important;
      letter-spacing: var(--booknook-reader-letter-spacing) !important;
    }
    ${protectedBody} {
      box-sizing: border-box !important;
      margin: 0 !important;
      max-width: none !important;
      padding-inline: var(--booknook-reader-padding-inline) !important;
      padding-top: var(--booknook-reader-padding-top) !important;
      padding-bottom: var(--booknook-reader-padding-bottom) !important;
      font-family: var(--booknook-reader-font-family) !important;
      font-size: var(--booknook-reader-font-size) !important;
      font-synthesis: none !important;
      line-height: var(--booknook-reader-line-height) !important;
    }
    ${fontOverride}
    ${lineHeightOverride}
    ${colorOverride}
    [data-booknook-smart-paragraph="true"] {
      ${paragraphSpacingRule}
      ${paragraphAlignment}
    }
    .booknook-smart-deduplicate-indent { text-indent: 0 !important; }
    .booknook-smart-auto-indent { text-indent: var(--booknook-reader-paragraph-indent) !important; }
    ${protectedBody} a { color: var(--booknook-reader-link) !important; }
    img, svg, video { max-width: 100% !important; height: auto !important; }
  `.trim();
}

const SMART_PARAGRAPH_ATTRIBUTE = 'data-booknook-smart-paragraph';
const SMART_INDENT_CLASSES = ['booknook-smart-deduplicate-indent', 'booknook-smart-auto-indent'] as const;
const UNSAFE_PARAGRAPH_CONTEXT = 'blockquote, pre, code, li, table, figure, figcaption, [role="heading"], [role="listitem"]';
const UNSAFE_PARAGRAPH_NAME = /(?:poem|poetry|verse|stanza|title|heading|subtitle|caption|code|preformatted)/i;
const LEADING_VISUAL_INDENT = /^(?:\u3000|\u00a0{2,}| {2,})/;

function clearSmartParagraphState(document: Document) {
  document.querySelectorAll<HTMLElement>(`[${SMART_PARAGRAPH_ATTRIBUTE}], .${SMART_INDENT_CLASSES[0]}, .${SMART_INDENT_CLASSES[1]}`).forEach((element) => {
    element.removeAttribute(SMART_PARAGRAPH_ATTRIBUTE);
    element.classList.remove(...SMART_INDENT_CLASSES);
  });
}

function paragraphIsSafe(element: HTMLParagraphElement) {
  if (element.closest(UNSAFE_PARAGRAPH_CONTEXT)) return false;
  let context: Element | null = element;
  while (context && context !== element.ownerDocument.body) {
    const semanticName = `${context.id} ${context.getAttribute('class') ?? ''}`;
    if (UNSAFE_PARAGRAPH_NAME.test(semanticName)) return false;
    context = context.parentElement;
  }
  if (element.children.length > 4 || element.querySelector('img, svg, video, audio, math, ruby, table')) return false;
  return Boolean(element.textContent?.trim());
}

/**
 * Marks visually safe body paragraphs without mutating EPUB text. Turning the
 * feature off removes only BookNook-owned markers, restoring publisher layout.
 */
export function applyEpubSmartTypography(document: Document, preferences: ReaderPreferences) {
  clearSmartParagraphState(document);
  const view = document.defaultView;
  document.querySelectorAll<HTMLParagraphElement>('p').forEach((paragraph) => {
    if (!paragraphIsSafe(paragraph)) return;
    paragraph.setAttribute(SMART_PARAGRAPH_ATTRIBUTE, 'true');
    if (!preferences.epub.optimization.enabled || !view) return;
    const hasLeadingIndent = LEADING_VISUAL_INDENT.test(paragraph.textContent ?? '');
    const computedIndent = Number.parseFloat(view.getComputedStyle(paragraph).textIndent);
    const hasPublisherIndent = Number.isFinite(computedIndent) && Math.abs(computedIndent) > 0.5;
    if (preferences.epub.optimization.deduplicateIndent && hasLeadingIndent && hasPublisherIndent) {
      paragraph.classList.add(SMART_INDENT_CLASSES[0]);
      return;
    }
    if (preferences.epub.optimization.indentUnindented && !hasLeadingIndent && !hasPublisherIndent) {
      paragraph.classList.add(SMART_INDENT_CLASSES[1]);
    }
  });
}

export function applyEpubThemeSnapshot(
  document: Document,
  preferences: ReaderPreferences,
  resolvedFont?: EpubFontResolution,
  viewportLayout: EpubViewportLayout = DEFAULT_EPUB_VIEWPORT_LAYOUT
) {
  const head = document.head ?? document.querySelector('head');
  if (!head) return;
  let style = head.querySelector<HTMLStyleElement>('style[data-booknook-reader-theme="v3"]');
  if (!style) {
    const namespace = document.documentElement?.namespaceURI;
    style = namespace
      ? document.createElementNS(namespace, 'style') as HTMLStyleElement
      : document.createElement('style');
    style.setAttribute('data-booknook-reader-theme', 'v3');
    head.append(style);
  }
  style.textContent = createEpubThemeSnapshot(preferences, resolvedFont, viewportLayout);
}

/**
 * epub.js applies pagination geometry as inline styles after spine hooks run.
 * This is the one post-layout writer for the page frame: it restores the
 * centered single-page measure and gives the text a stable vertical safe area.
 */
export function applyEpubDocumentSpacing(document: Document, preferences: ReaderPreferences) {
  const body = document.body;
  if (!body) return;
  const verticalSpacing = epubVerticalSpacing(preferences);

  body.style.setProperty('box-sizing', 'border-box', 'important');
  // The outer rendition viewport owns centering. A paginated EPUB iframe is
  // intentionally expanded to the width of every generated column; centering
  // or max-sizing body inside that expanded iframe shifts the column track and
  // makes two fragments appear in the visible viewport.
  body.style.setProperty('margin-left', '0', 'important');
  body.style.setProperty('margin-right', '0', 'important');
  body.style.setProperty('max-width', 'none', 'important');
  body.style.setProperty('padding-top', `var(--booknook-reader-padding-top, ${verticalSpacing})`, 'important');
  body.style.setProperty('padding-bottom', `var(--booknook-reader-padding-bottom, ${verticalSpacing})`, 'important');
  body.dataset.booknookPageLayout = preferences.epub.flow === 'paginated' ? 'single-centered' : 'scrolled-centered';
  applyEpubSmartTypography(document, preferences);
}
