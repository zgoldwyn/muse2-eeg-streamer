import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const protocolUrl = new URL("../src/protocol.json", import.meta.url);

test("the browser protocol uses only short demo durations", async () => {
  const protocol = JSON.parse(await readFile(protocolUrl, "utf8"));
  assert.equal(protocol.phases.length, 10);
  assert.equal(
    new Set(protocol.phases.map((phase) => phase.phaseId)).size,
    protocol.phases.length,
  );
  assert.equal(
    new Set(protocol.phases.map((phase) => phase.eventCode)).size,
    protocol.phases.length,
  );

  for (const phase of protocol.phases) {
    assert.equal(typeof phase.suggestedDuration.demoDurationSeconds, "number");
    assert.equal(phase.suggestedDuration.demoDurationSeconds, 4);
    assert.equal(
      Object.hasOwn(phase.suggestedDuration, "proposedParticipantProtocolSeconds"),
      false,
    );
  }
  assert.equal(
    protocol.phases.reduce(
      (total, phase) => total + phase.suggestedDuration.demoDurationSeconds,
      0,
    ),
    40,
  );
});
