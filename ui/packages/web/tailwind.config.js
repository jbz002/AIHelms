/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}', '../shared/src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      typography: {
        DEFAULT: {
          css: {
            'code::before': { content: '""' },
            'code::after': { content: '""' },
            code: {
              backgroundColor: '#f1f5f9',
              color: '#1e293b',
              fontWeight: '400',
              padding: '0.2em 0.4em',
              borderRadius: '0.25rem',
            },
            pre: {
              backgroundColor: '#f8fafc',
              color: '#334155',
              border: '1px solid #e2e8f0',
            },
            'pre code': {
              backgroundColor: 'transparent',
            },
          },
        },
      },
      animation: {
        'blob': 'blob 20s infinite',
        'blob-reverse': 'blob-reverse 25s infinite',
        'blob-slow': 'blob 30s infinite',
      },
      keyframes: {
        blob: {
          '0%, 100%': { transform: 'translate(0, 0) scale(1)' },
          '25%': { transform: 'translate(30px, -50px) scale(1.1)' },
          '50%': { transform: 'translate(-20px, 20px) scale(0.9)' },
          '75%': { transform: 'translate(20px, 40px) scale(1.05)' },
        },
        'blob-reverse': {
          '0%, 100%': { transform: 'translate(0, 0) scale(1)' },
          '25%': { transform: 'translate(-30px, 40px) scale(0.95)' },
          '50%': { transform: 'translate(20px, -30px) scale(1.1)' },
          '75%': { transform: 'translate(-20px, -20px) scale(1)' },
        },
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
