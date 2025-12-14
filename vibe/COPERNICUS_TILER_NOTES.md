# Copernicus DEM Tiler Notes

Date: 2025-12-11

## What we added
- Titiler-based Copernicus DEM service (port 8081) via `Dockerfile.copernicus_tiler` + `docker-compose.copernicus.yml`.
- Start/stop helper: `scripts/start_copernicus_service_docker.ps1` (uses compose; joins codex-network and shows up under the codex-container stack).

## How to test quickly
1) Pick a valid COG key from the bucket index: https://copernicus-dem-90m.s3.amazonaws.com/tileList.txt
2) Use the key verbatim in `url=`. Example (GLO-30/N30 W120):
   - Info: `http://localhost:8081/cog/info?url=https://copernicus-dem-90m.s3.amazonaws.com/Copernicus_DSM_COG_30_N30_00_W120_00_DEM/Copernicus_DSM_COG_30_N30_00_W120_00_DEM.tif`
   - TileJSON: `http://localhost:8081/cog/tilejson.json?url=https://copernicus-dem-90m.s3.amazonaws.com/Copernicus_DSM_COG_30_N30_00_W120_00_DEM/Copernicus_DSM_COG_30_N30_00_W120_00_DEM.tif&rescale=0,9000&nodata=0`
   - Tile (example inside footprint): `http://localhost:8081/cog/tiles/WebMercatorQuad/8/42/105?url=https://copernicus-dem-90m.s3.amazonaws.com/Copernicus_DSM_COG_30_N30_00_W120_00_DEM/Copernicus_DSM_COG_30_N30_00_W120_00_DEM.tif&rescale=0,9000&nodata=0`

## Gotchas we hit
- 404/500 was always due to bad keys or requesting tiles outside the asset footprint. Let `tilejson` guide x/y/z.
- Don’t add `.png` to the tiles route; Titiler expects `/cog/tiles/WebMercatorQuad/{z}/{x}/{y}`.
- Use HTTPS or s3://; bucket is public and works unsigned.

## How to consume in MapLibre (raster-dem)
Add a source:
```js
map.addSource('copernicus-dem', {
  type: 'raster-dem',
  url: 'http://localhost:8081/cog/tilejson.json?url=<<COG_URL>>&rescale=0,9000&nodata=0',
  tileSize: 256
});
map.setTerrain({source: 'copernicus-dem', exaggeration: 1.0});
```
Replace `<<COG_URL>>` with the exact COG URL from the bucket index.

## Next if we want a global terrain
- Either stitch a dynamic tiler that selects tiles by z/x/y, or stand up a Titiler STAC/mosaic backend.
- Alternatively, point to an existing public DEM mosaic service if we can trust availability and licensing.
