import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist/', 'src/api/schema.ts', 'coverage/'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  // правила хуков (exhaustive-deps и др.) — паритет с react-hooks/recommended
  reactHooks.configs.flat['recommended-latest'],
  {
    // set-state-in-effect (react-hooks v7) запрещает ЛЮБОЙ setState в
    // эффекте; у нас это штатные паттерны: реакция на статус задачи,
    // синхронизация формы с пришедшим detail, одноразовый bootstrap.
    files: ['**/*.{ts,tsx}'],
    rules: { 'react-hooks/set-state-in-effect': 'off' },
  },
  {
    files: ['**/*.{ts,tsx}'],
    rules: {
      // Единый ApiError с русскими текстами требует явного any в метаданных —
      // всё равно держим запрет, чтобы не размазать any по UI.
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { fixStyle: 'inline-type-imports' },
      ],
      eqeqeq: ['error', 'smart'],
      'no-console': ['error', { allow: ['warn', 'error'] }],
    },
  },
  {
    files: ['**/*.test.{ts,tsx}', 'src/test/**'],
    rules: { '@typescript-eslint/no-explicit-any': 'off' },
  },
)
