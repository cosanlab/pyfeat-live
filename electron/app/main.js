/******/ (() => { // webpackBootstrap
/******/ 	var __webpack_modules__ = ({

/***/ "env":
/*!**********************!*\
  !*** external "env" ***!
  \**********************/
/***/ ((module) => {

"use strict";
module.exports = require("env");

/***/ }),

/***/ "child_process":
/*!********************************!*\
  !*** external "child_process" ***!
  \********************************/
/***/ ((module) => {

"use strict";
module.exports = require("child_process");

/***/ }),

/***/ "path":
/*!***********************!*\
  !*** external "path" ***!
  \***********************/
/***/ ((module) => {

"use strict";
module.exports = require("path");

/***/ })

/******/ 	});
/************************************************************************/
/******/ 	// The module cache
/******/ 	var __webpack_module_cache__ = {};
/******/ 	
/******/ 	// The require function
/******/ 	function __webpack_require__(moduleId) {
/******/ 		// Check if module is in cache
/******/ 		var cachedModule = __webpack_module_cache__[moduleId];
/******/ 		if (cachedModule !== undefined) {
/******/ 			return cachedModule.exports;
/******/ 		}
/******/ 		// Create a new module (and put it into the cache)
/******/ 		var module = __webpack_module_cache__[moduleId] = {
/******/ 			// no module.id needed
/******/ 			// no module.loaded needed
/******/ 			exports: {}
/******/ 		};
/******/ 	
/******/ 		// Execute the module function
/******/ 		__webpack_modules__[moduleId](module, module.exports, __webpack_require__);
/******/ 	
/******/ 		// Return the exports of the module
/******/ 		return module.exports;
/******/ 	}
/******/ 	
/************************************************************************/
var __webpack_exports__ = {};
// This entry need to be wrapped in an IIFE because it need to be isolated against other modules in the chunk.
(() => {
/*!*********************!*\
  !*** ./src/main.js ***!
  \*********************/
// main.js

const path = __webpack_require__(/*! path */ "path");
const { spawn } = __webpack_require__(/*! child_process */ "child_process");
const env = __webpack_require__(/*! env */ "env"); // Assuming 'env' is a custom module or package for environment configuration

let serverCommand, serverArgs, serverOptions;

if (env.name === "development") {
    // In development, using 'poetry' to run the script
    serverCommand = "poetry";
    serverArgs = ["run", "python/pyfeatlive", "gui", "--electron"];
    serverOptions = undefined; // Default current working directory
} else {
    // In production, directly running the script
    serverCommand = "/Users/lukechang/Github/pyfeat-live/build/electron/app/python/pyfeatlive";
    serverArgs = ["gui", "--electron"];
    serverOptions = { cwd: "/Users/lukechang/Github/pyfeat-live/build/electron/app/python" };
}

const appStreamlitServer = spawn(serverCommand, serverArgs, serverOptions);

// Add necessary event listeners for the spawned process
appStreamlitServer.stdout.on("data", (data) => {
    console.log(`stdout: ${data}`);
});
appStreamlitServer.stderr.on("data", (data) => {
    console.error(`stderr: ${data}`);
});
appStreamlitServer.on('error', (error) => {
    console.error(`Error: ${error.message}`);
});
appStreamlitServer.on('close', (code) => {
    console.log(`Child process exited with code ${code}`);
});










})();

/******/ })()
;
//# sourceMappingURL=main.js.map