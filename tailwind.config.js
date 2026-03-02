/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./core/**/*.py",
    "./static/js/**/*.js",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
      },
      colors: {
        primary: {
          DEFAULT: "rgb(var(--color-primary) / <alpha-value>)",
          50: "rgb(var(--color-primary-50) / <alpha-value>)",
          100: "rgb(var(--color-primary-100) / <alpha-value>)",
          200: "rgb(var(--color-primary-200) / <alpha-value>)",
          500: "rgb(var(--color-primary) / <alpha-value>)",
          600: "rgb(var(--color-primary-600) / <alpha-value>)",
          700: "rgb(var(--color-primary-700) / <alpha-value>)",
        },
      },
      boxShadow: {
        soft: "0 2px 12px rgba(15, 23, 42, 0.06)",
        "soft-lg": "0 4px 24px rgba(15, 23, 42, 0.08)",
        card: "0 1px 3px rgba(15, 23, 42, 0.04), 0 4px 12px rgba(15, 23, 42, 0.04)",
        "card-hover": "0 4px 20px rgba(15, 23, 42, 0.08), 0 8px 24px rgba(249, 115, 22, 0.06)",
        glow: "0 0 24px rgba(249, 115, 22, 0.15)",
      },
      borderRadius: {
        xxl: "1rem",
        "3xl": "1.5rem",
        "4xl": "2rem",
      },
      maxWidth: {
        "8xl": "88rem",
        "9xl": "96rem",
      },
      spacing: {
        "18": "4.5rem",
        "22": "5.5rem",
      },
      animation: {
        "fade-up": "fadeUp 0.7s ease-out forwards",
        "fade-in": "fadeIn 0.7s ease-out forwards",
        "float": "float 6s ease-in-out infinite",
        "float-slow": "float 8s ease-in-out infinite",
        "scale-in": "scaleIn 0.6s ease-out forwards",
      },
      keyframes: {
        fadeUp: {
          "0%": { opacity: "0", transform: "translateY(16px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-12px)" },
        },
        scaleIn: {
          "0%": { opacity: "0", transform: "scale(0.95)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
      },
      transitionDuration: {
        700: "700ms",
      },
    },
    container: {
      center: true,
      padding: {
        DEFAULT: "1rem",
        sm: "1.5rem",
        lg: "2rem",
      },
      screens: {
        sm: "640px",
        md: "768px",
        lg: "1024px",
        xl: "1280px",
        "2xl": "1400px",
      },
    },
  },
  plugins: [],
};
