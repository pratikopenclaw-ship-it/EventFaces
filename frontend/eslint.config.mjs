import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import security from "eslint-plugin-security";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  security.configs.recommended,
  {
    rules: {
      // Disabled with justification (SECURITY_QA_REPORT.md, FE-SEC): it flags every obj[key],
      // including keys typed as TS literal unions and numeric indices. The only lookups with
      // network-derived keys use Object.hasOwn()/allowlists and have unit tests.
      "security/detect-object-injection": "off",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Vendored, self-hosted MediaPipe runtime (copied by scripts/fetch-mediapipe.mjs).
    "public/mediapipe/**",
  ]),
]);

export default eslintConfig;
