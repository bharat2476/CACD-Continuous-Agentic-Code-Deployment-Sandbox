const request = require('supertest');
const app = require('../server');

describe('CACD Sandbox API', () => {
  describe('GET /api/health', () => {
    it('returns 200 with service metadata', async () => {
      const res = await request(app).get('/api/health');
      expect(res.status).toBe(200);
      expect(res.body.status).toBe('ok');
      expect(res.body.service).toBe('cacd-sandbox-api');
      expect(res.body).toHaveProperty('timestamp');
      expect(res.body).toHaveProperty('uptimeSeconds');
    });
  });

  describe('GET /api/recommendations', () => {
    it('returns all recommendations by default', async () => {
      const res = await request(app).get('/api/recommendations');
      expect(res.status).toBe(200);
      expect(res.body.count).toBeGreaterThanOrEqual(3);
      expect(Array.isArray(res.body.data)).toBe(true);
      expect(res.body.data[0]).toHaveProperty('id');
      expect(res.body.data[0]).toHaveProperty('title');
    });

    it('filters by category query param', async () => {
      const res = await request(app).get('/api/recommendations?category=git');
      expect(res.status).toBe(200);
      expect(res.body.data.every((r) => r.category === 'git')).toBe(true);
    });

    it('filters by priority query param', async () => {
      const res = await request(app).get('/api/recommendations?priority=high');
      expect(res.status).toBe(200);
      expect(res.body.data.every((r) => r.priority === 'high')).toBe(true);
    });
  });

  describe('GET /api/recommendations/:id', () => {
    it('returns a single recommendation', async () => {
      const res = await request(app).get('/api/recommendations/rec-001');
      expect(res.status).toBe(200);
      expect(res.body.id).toBe('rec-001');
    });

    it('returns 404 for unknown id', async () => {
      const res = await request(app).get('/api/recommendations/missing');
      expect(res.status).toBe(404);
      expect(res.body.error).toBe('Recommendation not found');
    });
  });
});
