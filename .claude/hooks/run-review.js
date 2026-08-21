#!/usr/bin/env node

const https = require('https');
const { execSync } = require('child_process');

const OPENROUTER_API_KEY = process.env.OPENROUTER_API_KEY;
const OPENROUTER_API_URL = 'https://openrouter.ai/api/v1';

if (!OPENROUTER_API_KEY) {
  console.error('Error: OPENROUTER_API_KEY environment variable not set');
  process.exit(1);
}

async function runCodeReview() {
  try {
    // Get the full diff
    const diff = execSync('git diff HEAD', {
      encoding: 'utf-8',
      maxBuffer: 10 * 1024 * 1024 // 10MB buffer for large diffs
    });

    if (!diff.trim()) {
      console.log('No changes to review');
      return;
    }

    // Prepare the prompt for code review
    const systemPrompt = `You are an expert code reviewer. Analyze the provided git diff and provide constructive feedback on:
- Code quality and best practices
- Potential bugs or security issues
- Performance considerations
- Test coverage
- Documentation completeness

Be specific and actionable in your feedback.`;

    const userPrompt = `Please review the following code changes:\n\n\`\`\`diff\n${diff}\n\`\`\``;

    // Make request to OpenRouter
    const payload = JSON.stringify({
      model: 'claude-opus-4-1-20250805',
      messages: [
        {
          role: 'user',
          content: userPrompt
        }
      ],
      system: systemPrompt,
      max_tokens: 2048,
      temperature: 0.7
    });

    const options = {
      hostname: 'openrouter.ai',
      path: '/api/v1/chat/completions',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload),
        'Authorization': `Bearer ${OPENROUTER_API_KEY}`,
        'HTTP-Referer': 'https://dsg-cinema-proof-agent.local',
        'X-Title': 'DSG Cinema Code Review'
      }
    };

    return new Promise((resolve, reject) => {
      const req = https.request(options, (res) => {
        let data = '';

        res.on('data', (chunk) => {
          data += chunk;
        });

        res.on('end', () => {
          try {
            const response = JSON.parse(data);

            if (response.error) {
              console.error('OpenRouter API Error:', response.error.message);
              reject(new Error(response.error.message));
              return;
            }

            if (response.choices && response.choices[0]) {
              const review = response.choices[0].message.content;
              console.log('\n=== AUTOMATED CODE REVIEW ===\n');
              console.log(review);
              console.log('\n=============================\n');
              resolve(review);
            } else {
              console.error('Unexpected response format:', response);
              reject(new Error('Invalid response format'));
            }
          } catch (err) {
            reject(err);
          }
        });
      });

      req.on('error', (err) => {
        console.error('Request failed:', err.message);
        reject(err);
      });

      req.write(payload);
      req.end();
    });
  } catch (error) {
    console.error('Code review failed:', error.message);
    process.exit(1);
  }
}

runCodeReview().catch((err) => {
  console.error('Fatal error:', err.message);
  process.exit(1);
});
