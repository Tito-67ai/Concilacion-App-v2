/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{html,ts}",
  ],
  theme: {
    extend: {
      /* Sans geometrica moderna, como pide la guia visual: Inter o Roboto si
         estan instalados, y si no, la del sistema. Sin dependencia externa. */
      fontFamily: {
        sans: [
          'Inter',
          'Roboto',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
      },
    },
  },
  plugins: [],
}
