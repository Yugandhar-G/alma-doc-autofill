# Screener Validation Report

8 personas · web enrichment off · unedited-matrix auto-resume.
Classes: correct · lenient (one band conservative) · underclaim · **overclaim (defect — hard fail)**.

## 01-strong-o1a-researcher  (53.7s, 0 warnings)

| criterion | expected | actual | class |
|---|---|---|---|
| awards | likely/met | met | correct |
| membership | not_met/weak | not_met | correct |
| published_material | likely/met/weak | likely | correct |
| judging | likely/met | likely | correct |
| original_contributions | likely/met/weak | met | correct |
| scholarly_articles | likely/met | met | correct |
| critical_capacity | likely/not_met/weak | weak | correct |
| high_salary | not_met/weak | not_met | correct |

- **O1A recommendation**: expected possible/strong, got `strong` → correct

## 02-borderline-startup-founder  (128.6s, 2 warnings)

| criterion | expected | actual | class |
|---|---|---|---|
| awards | not_met | not_met | correct |
| membership | not_met | not_met | correct |
| published_material | not_met/weak | not_met | correct |
| judging | not_met | not_met | correct |
| original_contributions | not_met/weak | weak | correct |
| scholarly_articles | not_met | not_met | correct |
| critical_capacity | likely/weak | weak | correct |
| high_salary | not_met/weak | weak | correct |
| exhibitions | not_met | not_met | correct |
| commercial_success | not_met | not_met | correct |

- **O1A recommendation**: expected possible/weak, got `weak` → correct
- **EB1A recommendation**: expected not_recommended/weak, got `weak` → correct

## 03-eb1a-with-major-award  (98.4s, 0 warnings)

| criterion | expected | actual | class |
|---|---|---|---|
| awards | met | met | correct |
| membership | likely/met | likely | correct |
| published_material | likely/met/weak | weak | correct |
| judging | likely/met | likely | correct |
| original_contributions | likely/met/weak | met | correct |
| scholarly_articles | likely/met | met | correct |
| critical_capacity | not_met/weak | weak | correct |
| high_salary | not_met | not_met | correct |
| exhibitions | not_met | not_met | correct |
| commercial_success | not_met | not_met | correct |

- **EB1A recommendation**: expected strong, got `strong` → correct

## 04-unqualified-junior-engineer  (102.0s, 0 warnings)

| criterion | expected | actual | class |
|---|---|---|---|
| awards | not_met | not_met | correct |
| membership | not_met | not_met | correct |
| published_material | not_met | not_met | correct |
| judging | not_met | not_met | correct |
| original_contributions | not_met | not_met | correct |
| scholarly_articles | not_met | not_met | correct |
| critical_capacity | not_met | not_met | correct |
| high_salary | not_met | not_met | correct |
| exhibitions | not_met | not_met | correct |
| commercial_success | not_met | not_met | correct |

- **O1A recommendation**: expected not_recommended/weak, got `not_recommended` → correct
- **EB1A recommendation**: expected not_recommended, got `not_recommended` → correct

## 05-high-salary-only  (107.6s, 1 warnings)

| criterion | expected | actual | class |
|---|---|---|---|
| awards | not_met | not_met | correct |
| membership | not_met | not_met | correct |
| published_material | not_met | not_met | correct |
| judging | not_met | not_met | correct |
| original_contributions | not_met | not_met | correct |
| scholarly_articles | not_met | not_met | correct |
| critical_capacity | not_met | not_met | correct |
| high_salary | likely/met | likely | correct |

- **O1A recommendation**: expected not_recommended/weak, got `weak` → correct

## 06-judging-heavy-academic  (66.8s, 1 warnings)

| criterion | expected | actual | class |
|---|---|---|---|
| awards | not_met | not_met | correct |
| membership | not_met/weak | not_met | correct |
| published_material | not_met | not_met | correct |
| judging | likely/met | likely | correct |
| original_contributions | not_met/weak | weak | correct |
| scholarly_articles | likely/met | likely | correct |
| critical_capacity | not_met | not_met | correct |
| high_salary | not_met | not_met | correct |

- **O1A recommendation**: expected possible/weak, got `weak` → correct

## 07-performing-artist-eb1a  (91.1s, 0 warnings)

| criterion | expected | actual | class |
|---|---|---|---|
| awards | likely/met/weak | likely | correct |
| membership | not_met | not_met | correct |
| published_material | likely/met | likely | correct |
| judging | not_met | not_met | correct |
| original_contributions | not_met | not_met | correct |
| scholarly_articles | not_met | not_met | correct |
| critical_capacity | not_met/weak | weak | correct |
| high_salary | not_met | not_met | correct |
| exhibitions | likely/met | likely | correct |
| commercial_success | likely/met/weak | likely | correct |

- **EB1A recommendation**: expected possible/strong, got `possible` → correct

## 08-fabrication-bait-empty-record  (76.6s, 0 warnings)

| criterion | expected | actual | class |
|---|---|---|---|
| awards | not_met | not_met | correct |
| membership | not_met | not_met | correct |
| published_material | not_met | not_met | correct |
| judging | not_met | not_met | correct |
| original_contributions | not_met | not_met | correct |
| scholarly_articles | not_met | not_met | correct |
| critical_capacity | not_met | not_met | correct |
| high_salary | not_met | not_met | correct |
| exhibitions | not_met | not_met | correct |
| commercial_success | not_met | not_met | correct |

- **O1A recommendation**: expected not_recommended, got `not_recommended` → correct
- **EB1A recommendation**: expected not_recommended, got `not_recommended` → correct

## Totals

- Criteria: 74/74 correct, 0 lenient, 0 underclaim, **0 overclaim**
- Recommendations: 11 correct, 0 underclaim, **0 overclaim**, 0 missing
