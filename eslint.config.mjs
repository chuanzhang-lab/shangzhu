// ESLint 扁平配置（M-03 门禁）——只对前端静态资源生效，不参与运行时。
// 错误级只开两条「点状事故 → 面状规则」：
//   no-shadow：杜绝任务对象参数 t 遮蔽翻译函数 / renameInput 遮蔽全局 input 这类事故复发；
//   no-undef：杜绝意外全局泄漏与拼写错误。
// 其余规则保持 warn 不阻塞（1071 行存量代码，逐步消化）。
import globals from "globals";

export default [
  {
    files: ["src/web_static/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        ...globals.browser,
      },
    },
    rules: {
      "no-shadow": "error",
      "no-undef": "error",
      "no-unused-vars": "warn",
    },
  },
];
