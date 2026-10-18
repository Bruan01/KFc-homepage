interface Theme {
  "color-scheme": string
  "--color-base-100": string
  "--color-base-200": string
  "--color-base-300": string
  "--color-base-content": string
  "--color-primary": string
  "--color-primary-content": string
  "--color-secondary": string
  "--color-secondary-content": string
  "--color-accent": string
  "--color-accent-content": string
  "--color-neutral": string
  "--color-neutral-content": string
  "--color-info": string
  "--color-info-content": string
  "--color-success": string
  "--color-success-content": string
  "--color-warning": string
  "--color-warning-content": string
  "--color-error": string
  "--color-error-content": string
  "--radius-selector": string
  "--radius-field": string
  "--radius-box": string
  "--size-selector": string
  "--size-field": string
  "--border": string
  "--depth": string
  "--noise": string
}


interface Themes {
  synthwave: Theme
  dark: Theme
  corporate: Theme
  forest: Theme
  bumblebee: Theme
  retro: Theme
  night: Theme
  cmyk: Theme
  coffee: Theme
  dim: Theme
  nord: Theme
  abyss: Theme
  lofi: Theme
  silk: Theme
  valentine: Theme
  cyberpunk: Theme
  winter: Theme
  halloween: Theme
  luxury: Theme
  acid: Theme
  business: Theme
  aqua: Theme
  fantasy: Theme
  garden: Theme
  caramellatte: Theme
  autumn: Theme
  dracula: Theme
  light: Theme
  lemonade: Theme
  sunset: Theme
  black: Theme
  wireframe: Theme
  pastel: Theme
  cupcake: Theme
  emerald: Theme
  [key: string]: Theme
}

declare const themes: Themes
export default themes