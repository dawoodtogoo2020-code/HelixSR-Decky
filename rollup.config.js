import { readFileSync, existsSync, lstatSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, basename } from "node:path";
import replace from "@rollup/plugin-replace";
import typescript from "@rollup/plugin-typescript";
import externalGlobals from "rollup-plugin-external-globals";

const root = fileURLToPath(new URL(".", import.meta.url)).replace(/[\\/]$/, "");
const dist = fileURLToPath(new URL("./dist", import.meta.url));
const manifest = JSON.parse(readFileSync(new URL("./plugin.json", import.meta.url), "utf8"));
// Match Decky's official React/UI globals without its obsolete glob/delete chain.
export default {
  input: "./src/index.tsx",
  plugins: [
    { name: "clean-owned-dist", buildStart() {
      if (dirname(dist) !== root || basename(dist) !== "dist" || (existsSync(dist) && lstatSync(dist).isSymbolicLink())) {
        throw new Error("Refusing to clean a build path outside this plugin");
      }
      rmSync(dist, { recursive: true, force: true });
    } },
    typescript(),
    // Both bundled packages publish ESM. Decky provides React/UI at runtime.
    { name: "resolve-plugin-packages", resolveId(id) {
      if (id === "@decky/api" || id === "react-icons/fa") return fileURLToPath(import.meta.resolve(id));
      return null;
    } },
    externalGlobals({ react: "SP_REACT", "react/jsx-runtime": "SP_JSX", "react-dom": "SP_REACTDOM",
      "@decky/ui": "DFL", "@decky/manifest": JSON.stringify(manifest) }),
    replace({ preventAssignment: true, "process.env.NODE_ENV": JSON.stringify("production") }),
  ],
  context: "window",
  external: ["react", "react-dom", "@decky/ui"],
  onwarn(warning, warn) {
    if (warning.code === "UNRESOLVED_IMPORT") throw new Error(warning.message);
    warn(warning);
  },
  treeshake: { preset: "smallest" },
  output: { dir: "dist", format: "esm", sourcemap: true, exports: "default",
    sourcemapPathTransform: path => path.replace(/^\.\.\//, `decky://decky/plugin/${encodeURIComponent(manifest.name)}/`) },
};
