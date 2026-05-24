<template>
  <main class="page">
    <section class="header-band">
      <div>
        <p class="eyebrow">Region text fixture</p>
        <h1>通用区块文本抽取场景</h1>
      </div>
      <el-tag type="success">非站点特例</el-tag>
    </section>

    <section class="scenario-grid" aria-label="section text scenarios">
      <article class="scenario" data-testid="section-text-heading-sibling">
        <p class="scenario-label">可靠 anchor</p>
        <h2 data-testid="policy-heading">Warranty Policy</h2>
        <p data-testid="policy-body">
          The selected asset includes a two-year warranty, quarterly inspection records,
          and a local service response window of four business hours.
        </p>
      </article>

      <article class="scenario" data-testid="section-text-after-context-only">
        <p class="scenario-label">缺少前置 anchor</p>
        <p data-testid="orphan-body">
          This paragraph is intentionally placed before the nearest visible heading so a
          region selection over the paragraph should not promote the later heading as a
          deterministic section anchor.
        </p>
        <h2 data-testid="after-context-heading">Renewal Notes</h2>
      </article>

      <article class="scenario complex" data-testid="section-text-complex-container">
        <p class="scenario-label">复杂 container</p>
        <div class="nested-shell">
          <h2 data-testid="complex-heading">Risk Controls</h2>
          <div class="nested-body">
            <p data-testid="complex-body">
              Critical controls are split across nested layout blocks, badges, and supporting
              copy. Until compression can prove a stable container boundary, this fixture should
              remain a missing-anchor runtime AI candidate.
            </p>
            <ul>
              <li>Evidence review every 30 days</li>
              <li>Owner confirmation before renewal</li>
            </ul>
          </div>
        </div>
      </article>
    </section>
  </main>
</template>

<style scoped>
.page {
  min-height: 100%;
  background: #f5f7fb;
  color: #1f2937;
}

.header-band {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 28px 32px;
  background: #ffffff;
  border-bottom: 1px solid #d9e0ea;
}

.eyebrow,
.scenario-label {
  margin: 0 0 8px;
  color: #5b6472;
  font-size: 13px;
}

h1,
h2,
p {
  margin-top: 0;
}

h1 {
  margin-bottom: 0;
  font-size: 24px;
  font-weight: 700;
}

h2 {
  margin-bottom: 12px;
  font-size: 18px;
  font-weight: 700;
}

.scenario-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 18px;
  padding: 24px 32px;
}

.scenario {
  min-height: 260px;
  padding: 20px;
  background: #ffffff;
  border: 1px solid #d9e0ea;
  border-radius: 8px;
}

.scenario p:not(.scenario-label) {
  color: #374151;
  line-height: 1.7;
}

.complex {
  background: #fbfcff;
}

.nested-shell {
  padding: 16px;
  border: 1px solid #c8d3e2;
  border-radius: 6px;
  background: #ffffff;
}

.nested-body {
  display: grid;
  gap: 12px;
  padding: 14px;
  border-left: 3px solid #2f81f7;
  background: #f7faff;
}

ul {
  margin: 0;
  padding-left: 20px;
  color: #374151;
  line-height: 1.7;
}
</style>
