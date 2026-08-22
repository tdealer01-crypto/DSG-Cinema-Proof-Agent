#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execSync } = require('child_process');

const gitDir = path.join(process.cwd(), '.git');
const lastDiffFile = path.join(gitDir, 'redline-last-diff');

try {
  // Get the diff summary
  const diffStat = execSync('git diff --stat HEAD', {
    encoding: 'utf-8',
    stdio: ['pipe', 'pipe', 'pipe']
  }).trim();

  if (!diffStat) {
    // No changes
    console.log(JSON.stringify({
      decision: 'skip',
      reason: 'No changes detected'
    }));
    process.exit(0);
  }

  // Hash the diff
  const hash = crypto.createHash('md5').update(diffStat).digest('hex');

  // Read last hash if it exists
  let lastHash = null;
  if (fs.existsSync(lastDiffFile)) {
    lastHash = fs.readFileSync(lastDiffFile, 'utf-8').trim();
  }

  // Check if diff has changed
  if (hash === lastHash) {
    console.log(JSON.stringify({
      decision: 'skip',
      reason: 'Same diff as last review, no new changes'
    }));
    process.exit(0);
  }

  // Save the new hash
  fs.writeFileSync(lastDiffFile, hash);

  // Output decision to block (trigger review)
  console.log(JSON.stringify({
    decision: 'block',
    reason: `Code changes detected:\n${diffStat}`,
    diffSummary: diffStat
  }));

  process.exit(0);
} catch (error) {
  // If any error, skip the check
  console.log(JSON.stringify({
    decision: 'skip',
    reason: `Check failed: ${error.message}`
  }));
  process.exit(0);
}
