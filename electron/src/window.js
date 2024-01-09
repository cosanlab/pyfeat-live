// window.js
// This electron app is based off of a tutorial by Simon Biggs for PyMedPhys: 
// https://docs.pymedphys.com/en/continue-binary/contrib/dive/create-streamlit-exe.html#

const { app, BrowserWindow, screen } = require("electron");
const jetpack = require("fs-jetpack");

const createWindow = (name, options) => {
    const userDataDir = jetpack.cwd(app.getPath("userData"));
    const stateStoreFile = `window-state-${name}.json`;
    const defaultSize = { width: options.width, height: options.height };
    let state = {};

    const restore = () => {
        try {
            return { ...defaultSize, ...userDataDir.read(stateStoreFile, "json") };
        } catch (err) {
            return defaultSize;
        }
    };

    const getCurrentPosition = () => {
        const [x, y] = win.getPosition();
        const [width, height] = win.getSize();
        return { x, y, width, height };
    };

    const windowWithinBounds = (windowState, bounds) => {
        return (
            windowState.x >= bounds.x &&
            windowState.y >= bounds.y &&
            windowState.x + windowState.width <= bounds.x + bounds.width &&
            windowState.y + windowState.height <= bounds.y + bounds.height
        );
    };

    const resetToDefaults = () => {
        const { width, height } = screen.getPrimaryDisplay().bounds;
        return {
            ...defaultSize,
            x: (width - defaultSize.width) / 2,
            y: (height - defaultSize.height) / 2
        };
    };

    const ensureVisibleOnSomeDisplay = (windowState) => {
        const visible = screen.getAllDisplays().some(display => windowWithinBounds(windowState, display.bounds));
        return visible ? windowState : resetToDefaults();
    };

    const saveState = () => {
        if (!win.isMinimized() && !win.isMaximized()) {
            Object.assign(state, getCurrentPosition());
        }
        userDataDir.write(stateStoreFile, state, { atomic: true });
    };

    state = ensureVisibleOnSomeDisplay(restore());
    const win = new BrowserWindow({ ...options, ...state });
    win.on("close", saveState);

    return win;
};

module.exports = createWindow;

