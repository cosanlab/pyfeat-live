import { mount } from 'svelte';
import App from './App.svelte';
import './app.css';

// Guard against the webview navigating to a dropped file. When a video is
// dragged onto the window but MISSES the Extract dropzone, the browser's
// default action opens the file (file://…) and replaces the whole app with a
// bare video player you can't escape. The dropzone keeps its own
// ondragover/ondrop for visual feedback + file ingest; these document-level
// listeners fire last (bubble phase) and only suppress the default file-open
// for drops that land anywhere else.
window.addEventListener('dragover', (e) => e.preventDefault());
window.addEventListener('drop', (e) => e.preventDefault());

const target = document.getElementById('app');
if (!target) throw new Error('#app not found');

const app = mount(App, { target });

export default app;
