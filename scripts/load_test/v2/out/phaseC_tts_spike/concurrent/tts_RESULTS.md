# Load campaign — tts :8011

- warm baseline p95: 819 ms
- knee (max sustainable concurrency): **4**

| concurrency | ok | failed | err% | p50 ms | p95 ms | p99 ms | max ms | req/s |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 29 | 0 | 0.0 | 779 | 819 | 844 | 844 | 1.3 |
| 2 | 50 | 0 | 0.0 | 878 | 941 | 952 | 952 | 2.3 |
| 4 | 97 | 0 | 0.0 | 917 | 975 | 1019 | 1019 | 4.3 |
| 8 | 104 | 0 | 0.0 | 1816 | 1919 | 1985 | 1988 | 4.4 |
