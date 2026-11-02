# Load campaign — tts :8011

- warm baseline p95: 839 ms
- knee (max sustainable concurrency): **1**

| concurrency | ok | failed | err% | p50 ms | p95 ms | p99 ms | max ms | req/s |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 23 | 0 | 0.0 | 775 | 839 | 849 | 849 | 1.3 |
| 2 | 25 | 0 | 0.0 | 1551 | 1608 | 1673 | 1673 | 1.3 |
