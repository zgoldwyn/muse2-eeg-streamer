import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const fixtureUrl = new URL("../src/session-metadata.json", import.meta.url);

test("synthetic session metadata matches the shared recorder schema", async () => {
  const metadata = JSON.parse(await readFile(fixtureUrl, "utf8"));

  assert.deepEqual(Object.keys(metadata).sort(), [
    "nominal_sample_rate_hz",
    "samples_per_packet",
  ]);
  assert.equal(metadata.nominal_sample_rate_hz, 256);
  assert.equal(metadata.samples_per_packet, 12);
});