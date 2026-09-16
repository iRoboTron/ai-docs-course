/* Shared by the browser and node regression tests; no network or DOM required. */
(function (root) {
    'use strict';
    function slug(text) {
        return text.trim().toLowerCase().replace(/[^\p{L}\p{N}\s_-]/gu, '').replace(/\s+/g, '-');
    }
    function resolve(href, course, file, courses) {
        if (!href || /^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(href)) return null;
        if (href.startsWith('#')) {
            const fragment = decodeURIComponent(href.slice(1));
            if (!fragment) return '#top';
            const files = (courses[course] || []).map(i => typeof i === 'string' ? i : i.file);
            if (files.some(f => f.replace(/\.md$/, '') === fragment)) return href;
            return '#' + file.replace(/\.md$/, '') + '--' + fragment;
        }
        const url = new URL(href, `https://course.invalid/books/${course}/${file}`);
        const match = decodeURIComponent(url.pathname).match(/^\/books\/([^/]+)\/([^/]+\.md)$/);
        if (!match) return null;
        const [, targetCourse, targetFile] = match;
        if (!(courses[targetCourse] || []).some(i => (typeof i === 'string' ? i : i.file) === targetFile)) return null;
        const section = targetFile.replace(/\.md$/, '');
        const anchor = section + (url.hash ? '--' + decodeURIComponent(url.hash.slice(1)) : '');
        if (targetCourse === course) return '#' + anchor;
        const number = Number(targetCourse.match(/^\d+/)[0]);
        return `reader.html?b=${number}&c=${encodeURIComponent(section)}#${encodeURIComponent(anchor)}`;
    }
    const api = { slug, resolve };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.ReaderLinks = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
