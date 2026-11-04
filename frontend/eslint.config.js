import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'

export default tseslint.config(
  // Thư mục worktree tạm mà agent dựng ra, mỗi cái là một BẢN SAO đầy đủ của
  // `src/`. Git đã loại chúng qua `.git/info/exclude`, nhưng eslint thì chưa, nên
  // `make lint` quét cả bản sao và báo lại y nguyên mọi cảnh báo của repo gốc —
  // số cảnh báo nhân đôi, và với `--max-warnings 0` là ĐỎ vì một file không ai
  // đang sửa. Đã gặp thật 2026-08-07 (khi đó worktree ở `.claude/worktrees/`).
  //
  // ⚠ PHẢI LIỆT KÊ CẢ HAI ĐƯỜNG DẪN. Bẫy này đã sập LẦN THỨ HAI 2026-08-27: chỗ
  // dựng worktree đổi sang `.worktrees/` mà ignore vẫn chỉ có `.claude`, nên
  // `make lint` đỏ trở lại y hệt lần đầu — cùng một lỗi, khác một cái tên thư mục.
  // Thêm chỗ dựng worktree mới thì thêm một dòng vào đây.
  {
    ignores: ['dist', 'node_modules', '.claude', '.worktrees', 'src/routeTree.gen.ts'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],

      // TS strict, no `any` — spec §6.1. `any` là lỗi, không phải cảnh báo.
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/consistent-type-imports': 'error',
    },
  },

  /**
   * Ranh giới module — Luật 3 của repo, bản FE. CHỈ áp cho file trong
   * `src/features/**`: một module không được trèo ra module bên cạnh bằng
   * đường tương đối.
   *
   * Luật này cố ý HẸP. Đường alias (`@/features/agent/x`) do
   * `tests/module-boundaries.test.ts` bắt — nó quét văn bản nên thấy cả hai
   * dạng, còn `no-restricted-imports` chỉ khớp được pattern đường dẫn.
   * Eslint để bắt lúc đang viết; test để CI không cho merge.
   */
  {
    files: ['src/features/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['../*/*', '!../*/contracts', '!../*/contracts/*'],
              message:
                'Cấm import ruột module khác. Chỉ được import features/<khác>/contracts. Xem README.md §Ranh giới module.',
            },
          ],
        },
      ],
    },
  },

  /**
   * Cặp Provider + hook trong cùng một file là idiom React chuẩn
   * (`<LangProvider>` + `useLang()`), nhưng nó phá điều kiện fast-refresh.
   * Đánh đổi có chủ ý: tách hook ra file riêng làm hai file phải đọc cùng lúc
   * để hiểu một thứ. Fast-refresh chậm hơn một nhịp ở ba file này (2026-09-28
   * thêm `LopPhu.tsx` — cùng idiom, khối lớp phủ tablet/mobile), đổi lấy một
   * seam đọc được trong một lần mở.
   */
  {
    files: ['src/i18n/index.tsx', 'src/lib/session.tsx', 'src/components/shell/LopPhu.tsx'],
    rules: { 'react-refresh/only-export-components': 'off' },
  },
)
