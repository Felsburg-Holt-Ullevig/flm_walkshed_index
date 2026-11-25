/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Optional replacement for the OIT vector tile service address. */
  readonly VITE_OIT_VECTOR_BASEMAP_URL?: string;
  /** Optional replacement for the OIT dynamic map service address. */
  readonly VITE_OIT_RASTER_BASEMAP_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
