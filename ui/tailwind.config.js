/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  corePlugins: { preflight: false }, // antd ships its own reset
  theme: {
    extend: {
      colors: { brand: '#16303d', accent: '#2ed88e', mint: '#ddfff2' },
      fontFamily: { sans: ['Poppins', 'system-ui', 'sans-serif'] },
    },
  },
  plugins: [],
}
