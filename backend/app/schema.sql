CREATE TABLE IF NOT EXISTS providers (
    id text PRIMARY KEY,
    name text NOT NULL,
    doc text
);

CREATE TABLE IF NOT EXISTS catalogue_model_keys (
    model_key text PRIMARY KEY,
    model_id uuid NOT NULL
);
CREATE TABLE IF NOT EXISTS catalogue_model_redirects (
    source_id uuid PRIMARY KEY,
    target_id uuid NOT NULL,
    CHECK (source_id <> target_id)
);
CREATE TABLE IF NOT EXISTS catalogue_models (
    id uuid PRIMARY KEY,
    model_id text UNIQUE NOT NULL,
    name text NOT NULL,
    publisher text,
    context_tokens bigint,
    output_tokens bigint,
    input_price double precision,
    output_price double precision,
    reasoning boolean,
    tool_call boolean,
    open_weights boolean,
    azure_support text NOT NULL CHECK (azure_support IN ('listed', 'not_listed', 'unknown')),
    pricing_provider_id text,
    azure_names text[] NOT NULL,
    raw jsonb NOT NULL,
    metadata jsonb,
    azure_observations jsonb NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS catalogue_models_name_idx ON catalogue_models(lower(name), model_id);

CREATE TABLE IF NOT EXISTS models (
    id uuid PRIMARY KEY,
    provider_id text NOT NULL REFERENCES providers(id),
    model_id text NOT NULL,
    name text NOT NULL,
    metadata_id text,
    metadata_match text,
    context_tokens bigint,
    output_tokens bigint,
    input_price double precision,
    output_price double precision,
    reasoning boolean,
    tool_call boolean,
    open_weights boolean,
    raw jsonb NOT NULL,
    metadata jsonb,
    catalogue_id uuid REFERENCES catalogue_models(id),
    UNIQUE (provider_id, model_id)
);
CREATE INDEX IF NOT EXISTS models_provider_idx ON models(provider_id);
CREATE INDEX IF NOT EXISTS models_name_idx ON models(lower(name));

CREATE TABLE IF NOT EXISTS azure_models (
    location text NOT NULL,
    model_name text NOT NULL,
    version text NOT NULL,
    raw jsonb NOT NULL,
    PRIMARY KEY (location, model_name, version)
);

CREATE TABLE IF NOT EXISTS seed_state (
    id integer PRIMARY KEY CHECK (id = 1),
    seeded_at timestamptz NOT NULL,
    model_count integer NOT NULL,
    sources jsonb NOT NULL,
    catalogue_count integer
);
