# Work in progress: JavaScript-driven native UI

These files are not compiled (the build only uses `shell/Sources`). They run
`app/main.js` in JavaScriptCore with timers, fetch, storage, sandboxed files,
`require` and the `tux` sensor API, and let the script describe a SwiftUI view
tree. The renderer that turns those `Node`/`Props` trees into SwiftUI views
is not written yet, so moving these into `Sources/` will not compile.
