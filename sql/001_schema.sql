CREATE TABLE IF NOT EXISTS geo.data_versions (
    city TEXT PRIMARY KEY,
    data_version TEXT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS geo.hex_features (
    city TEXT NOT NULL,
    h3 TEXT NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    district TEXT NOT NULL,
    residents DOUBLE PRECISION NOT NULL CHECK (residents >= 0),
    workers DOUBLE PRECISION NOT NULL CHECK (workers >= 0),
    offices_n INTEGER NOT NULL CHECK (offices_n >= 0),
    education_n INTEGER NOT NULL CHECK (education_n >= 0),
    malls_n INTEGER NOT NULL CHECK (malls_n >= 0),
    transit_stops_n INTEGER NOT NULL CHECK (transit_stops_n >= 0),
    metro_dist_m DOUBLE PRECISION,
    geom GEOMETRY(POINT, 4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lon, lat), 4326)) STORED,
    PRIMARY KEY (city, h3)
);

CREATE TABLE IF NOT EXISTS geo.competitors (
    city TEXT NOT NULL,
    poi_id TEXT NOT NULL,
    niche TEXT NOT NULL,
    name TEXT NOT NULL,
    brand TEXT,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    h3 TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('osm', 'mos_ru')),
    seats INTEGER CHECK (seats >= 0),
    geom GEOMETRY(POINT, 4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lon, lat), 4326)) STORED,
    PRIMARY KEY (city, niche, poi_id)
);

CREATE INDEX IF NOT EXISTS competitors_geom_idx ON geo.competitors USING GIST (geom);

CREATE TABLE IF NOT EXISTS geo.addresses (
    city TEXT NOT NULL,
    address TEXT NOT NULL,
    address_search TEXT NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    h3 TEXT NOT NULL,
    geom GEOMETRY(POINT, 4326) GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(lon, lat), 4326)) STORED,
    PRIMARY KEY (city, address)
);

CREATE INDEX IF NOT EXISTS addresses_search_idx ON geo.addresses USING GIN (address_search gin_trgm_ops);

CREATE TABLE IF NOT EXISTS geo.scores (
    city TEXT NOT NULL,
    niche TEXT NOT NULL,
    h3 TEXT NOT NULL,
    revenue_p10 DOUBLE PRECISION NOT NULL,
    revenue_p50 DOUBLE PRECISION NOT NULL,
    revenue_p90 DOUBLE PRECISION NOT NULL,
    profit_p50 DOUBLE PRECISION NOT NULL,
    payback_months_p50 DOUBLE PRECISION,
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high')),
    competitors_500m INTEGER NOT NULL CHECK (competitors_500m >= 0),
    PRIMARY KEY (city, niche, h3),
    CHECK (revenue_p10 <= revenue_p50 AND revenue_p50 <= revenue_p90)
);
