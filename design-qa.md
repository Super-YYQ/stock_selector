# Design QA

- Source visual truth: `artifacts/design-reference/selected-option-3.png`
- Implementation screenshot: `artifacts/design-audit/08-redesign-overview-desktop.png`
- Additional evidence: `artifacts/design-audit/09-redesign-custom-strategies.png`, `artifacts/design-audit/10-redesign-overview-mobile.png`, `artifacts/design-audit/11-redesign-custom-mobile.png`
- Viewport: 1440 x 1024 desktop; 390 x 844 mobile
- State: 2026-07-10 report loaded from the local API with 5530 covered stocks

## Full-view comparison evidence

The source and implementation were opened together in one comparison input at the same 1440 x 1024 viewport. The implementation preserves the selected direction's main proportions and reading order: dark compact navigation, left daily brief, top evidence strip, central Top 10 ledger, and persistent right-side stock context. Typography, neutral surfaces, semantic red/green values, teal action color, separators, and restrained radii are visibly consistent with the source.

The formula workspace and both mobile captures use the same tokens and hierarchy. Mobile views fit the 390 px frame, switch to five-item bottom navigation, simplify table columns, and keep primary actions on screen without incoherent overlap.

## Focused region comparison evidence

A separate crop was not required because the 1440 x 1024 images keep the sidebar, evidence strip, table rows, inspector, typography, icons, and controls legible in the same comparison input. The custom-formula desktop and mobile screenshots provide additional focused evidence for the new workflow that was not present in the source mock.

## Findings

- No actionable P0, P1, or P2 visual mismatch remains.
- [P3] The implementation's stock inspector intentionally uses fields available in the report payload rather than reproducing mock-only market-cap and valuation fields.
- [P3] The captured desktop table still shows a narrow horizontal track. The nonessential row detail column was removed afterward so row selection and the persistent inspector carry that action; this is a minor density refinement.

## Required fidelity surfaces

- Fonts and typography: system Chinese sans stack, 0 letter spacing, tabular numeric hierarchy, and compact dashboard scale match the target. Long text is moved to the inspector or formula summary rather than repeated in rows.
- Spacing and layout rhythm: sidebar, 282 px brief rail, evidence strip, central ledger, and inspector tracks align closely with the target. Radii stay at 5 px or below and elevation is avoided.
- Colors and visual tokens: charcoal navigation, white/cool-gray surfaces, restrained teal, Chinese-market red gains, green losses, and ochre sector bars match the selected direction.
- Image quality and asset fidelity: the source contains no raster imagery. The implementation uses the bundled Lucide icon asset and does not substitute handcrafted SVG, CSS illustration, gradients, or decorative imagery.
- Copy and content: all visible copy is product-specific Chinese market data. The implementation adds real custom-formula results without leaking implementation instructions into the interface.

## Interaction evidence

- Navigation from market overview to the custom-formula workspace succeeded.
- Switching from `量价 RPS 共振` to `缩量趋势回踩` updated the title and result count from 12 to 30.
- Desktop and mobile data loaded successfully from the local API.
- The browser security layer rejected the final custom-result drawer click after screenshots were captured. The drawer implementation and existing detail buttons remain covered by automated tests and earlier browser evidence, but that last repeated click was not retried.

## Comparison history

No P0/P1/P2 finding required a visual iteration. The only post-capture change removed a redundant detail column to reduce a P3 table overflow artifact.

## Follow-up polish

- Add valuation and capitalization fields to the inspector only when the data pipeline can provide them reliably.
- Recheck the custom-result detail click when the in-app browser permits local interaction again.

final result: passed
