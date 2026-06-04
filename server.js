const express = require('express');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());

const recommendations = [
  {
    id: 'rec-001',
    title: 'Enable trunk-based development',
    category: 'process',
    priority: 'high',
    summary: 'Short-lived branches merged frequently into main reduce merge conflicts.',
  },
  {
    id: 'rec-002',
    title: 'Require linear history on main',
    category: 'git',
    priority: 'high',
    summary: 'Rebase or squash merges prevent parallel histories that overwrite concurrent work.',
  },
  {
    id: 'rec-003',
    title: 'Gate production with agentic review',
    category: 'security',
    priority: 'medium',
    summary: 'Multi-agent PR analysis catches structural and security regressions before QA.',
  },
];

app.get('/api/health', (req, res) => {
  res.status(200).json({
    status: 'ok',
    service: 'cacd-sandbox-api',
    version: process.env.npm_package_version || '1.0.0',
    uptimeSeconds: Math.floor(process.uptime()),
    timestamp: new Date().toISOString(),
  });
});

app.get('/api/recommendations', (req, res) => {
  const { category, priority } = req.query;
  let results = [...recommendations];

  if (category) {
    results = results.filter((r) => r.category === String(category).toLowerCase());
  }
  if (priority) {
    results = results.filter((r) => r.priority === String(priority).toLowerCase());
  }

  res.status(200).json({
    count: results.length,
    data: results,
  });
});

app.get('/api/recommendations/:id', (req, res) => {
  const item = recommendations.find((r) => r.id === req.params.id);
  if (!item) {
    return res.status(404).json({ error: 'Recommendation not found', id: req.params.id });
  }
  return res.status(200).json(item);
});

if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`CACD sandbox API listening on port ${PORT}`);
  });
}

module.exports = app;
