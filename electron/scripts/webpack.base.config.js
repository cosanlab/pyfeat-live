// This electron app is based off of a tutorial by Simon Biggs for PyMedPhys: 
// https://docs.pymedphys.com/en/continue-binary/contrib/dive/create-streamlit-exe.html#

const path = require("path");
const nodeExternals = require("webpack-node-externals");

const determineEnvironment = (env) => {
    return env.production ? "production" : env.test ? "test" : "development";
};

const determineMode = (env) => {
    return env.production ? "production" : "development";
};

module.exports = (env) => ({
    target: "electron-renderer",
    mode: determineMode(env),
    node: {
        __dirname: false,
        __filename: false
    },
    externals: [nodeExternals()],
    resolve: {
        alias: {
            env: path.resolve(__dirname, `../config/env_${determineEnvironment(env)}.json`)
        },
        extensions: ['.js'],
    },
    experiments: {
        topLevelAwait: true
    },
    devtool: "source-map",
    module: {
        rules: []
        // Removed TypeScript loader
    },
});
