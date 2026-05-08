import SwiftUI

enum Theme {
    /// Palette values are sourced from `DesignTokens` (generated from
    /// `design-tokens/tokens.json`). `Theme.Palette` stays as the public API
    /// so call sites don't need to change when tokens are renamed or restructured.
    enum Palette {
        static let cream = DesignTokens.colorCream
        static let creamDeep = DesignTokens.colorCreamDeep
        static let ink = DesignTokens.colorInk
        static let inkSoft = DesignTokens.colorInkSoft
        static let muted = DesignTokens.colorMuted
        static let amber = DesignTokens.colorAmber
        static let amberDeep = DesignTokens.colorAmberDeep
        static let rule = DesignTokens.colorRule
        static let cardShadow = Color.black.opacity(0.06)
    }

    // Type ramp. Six base tiers + two emphasis variants. All text is sentence
    // case; only `MetaLabel` uppercases (eyebrow style). Mono and SF Symbol
    // sizing is intentionally outside this ramp.
    //
    // Sourced from `DesignTokens` (generated from `design-tokens/tokens.json`).
    enum Typography {
        static let display = DesignTokens.typographyDisplay
        static let title = DesignTokens.typographyTitle
        static let subtitle = DesignTokens.typographySubtitle
        static let body = DesignTokens.typographyBody
        static let bodyStrong = DesignTokens.typographyBodyStrong
        static let callout = DesignTokens.typographyCallout
        static let calloutStrong = DesignTokens.typographyCalloutStrong
        static let meta = DesignTokens.typographyMeta
    }

    enum Spacing {
        static let xs = DesignTokens.spacingXs
        static let s = DesignTokens.spacingS
        static let m = DesignTokens.spacingM
        static let l = DesignTokens.spacingL
        static let xl = DesignTokens.spacingXl
    }

    static let cardRadius = DesignTokens.radiusCard
}

struct EditorialBackground: ViewModifier {
    func body(content: Content) -> some View {
        ZStack {
            Theme.Palette.cream.ignoresSafeArea()
            content
        }
        .scrollContentBackground(.hidden)
        .toolbarBackground(Theme.Palette.cream, for: .navigationBar)
        .toolbarBackground(.visible, for: .navigationBar)
        .toolbarBackground(Theme.Palette.cream, for: .tabBar)
    }
}

extension View {
    func editorialBackground() -> some View { modifier(EditorialBackground()) }
}

struct MetaLabel: View {
    let text: String
    var body: some View {
        Text(text.uppercased())
            .font(Theme.Typography.meta)
            .tracking(1.4)
            .foregroundStyle(Theme.Palette.amberDeep)
    }
}

struct EditorialCard<Content: View>: View {
    let content: () -> Content
    init(@ViewBuilder content: @escaping () -> Content) { self.content = content }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.m) {
            content()
        }
        .padding(Theme.Spacing.l)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                .fill(Color.white)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                .stroke(Theme.Palette.rule, lineWidth: 0.5)
        )
        .shadow(color: Theme.Palette.cardShadow, radius: 8, y: 2)
    }
}

struct AmberButtonStyle: ButtonStyle {
    enum Variant { case filled, outlined }
    var variant: Variant = .filled

    func makeBody(configuration: Configuration) -> some View {
        let isFilled = variant == .filled
        return configuration.label
            .font(.system(size: 16, weight: .semibold))
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14)
            .background(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(isFilled ? Theme.Palette.amber : Color.clear)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(Theme.Palette.amber, lineWidth: isFilled ? 0 : 1.5)
            )
            .foregroundStyle(isFilled ? Color.white : Theme.Palette.amberDeep)
            .opacity(configuration.isPressed ? 0.85 : 1)
    }
}

extension ButtonStyle where Self == AmberButtonStyle {
    static var amberFilled: AmberButtonStyle { AmberButtonStyle(variant: .filled) }
    static var amberOutlined: AmberButtonStyle { AmberButtonStyle(variant: .outlined) }
}

struct EditorialDivider: View {
    var body: some View {
        Rectangle()
            .fill(Theme.Palette.rule)
            .frame(height: 0.5)
    }
}

struct ChecklistRow: View {
    let label: String
    let isComplete: Bool
    var body: some View {
        HStack(spacing: Theme.Spacing.s) {
            Image(systemName: isComplete ? "checkmark.circle.fill" : "circle")
                .foregroundStyle(isComplete ? Theme.Palette.amber : Theme.Palette.muted)
                .font(.system(size: 18))
            Text(label)
                .font(Theme.Typography.body)
                .foregroundStyle(isComplete ? Theme.Palette.muted : Theme.Palette.ink)
                .strikethrough(isComplete, color: Theme.Palette.muted)
            Spacer()
        }
    }
}
