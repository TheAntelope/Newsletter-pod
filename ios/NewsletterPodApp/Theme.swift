import SwiftUI

enum Theme {
    enum Palette {
        static let cream = Color(red: 0.961, green: 0.941, blue: 0.902)
        static let creamDeep = Color(red: 0.929, green: 0.902, blue: 0.851)
        static let ink = Color(red: 0.110, green: 0.102, blue: 0.090)
        static let inkSoft = Color(red: 0.247, green: 0.231, blue: 0.208)
        static let muted = Color(red: 0.420, green: 0.388, blue: 0.349)
        static let amber = Color(red: 0.722, green: 0.392, blue: 0.165)
        static let amberDeep = Color(red: 0.580, green: 0.298, blue: 0.106)
        static let rule = Color(red: 0.851, green: 0.820, blue: 0.761)
        static let cardShadow = Color.black.opacity(0.06)
    }

    // Type ramp. Six base tiers + two emphasis variants. All text is sentence
    // case; only `MetaLabel` uppercases (eyebrow style). Mono and SF Symbol
    // sizing is intentionally outside this ramp.
    enum Typography {
        static let display: Font = .system(size: 32, weight: .bold, design: .serif)
        static let title: Font = .system(size: 22, weight: .semibold, design: .serif)
        static let subtitle: Font = .system(size: 17, weight: .semibold, design: .serif)
        static let body: Font = .system(size: 15, weight: .regular, design: .default)
        static let bodyStrong: Font = .system(size: 15, weight: .semibold, design: .default)
        static let callout: Font = .system(size: 13, weight: .regular, design: .default)
        static let calloutStrong: Font = .system(size: 13, weight: .semibold, design: .default)
        static let meta: Font = .system(size: 11, weight: .semibold, design: .default)
    }

    enum Spacing {
        static let xs: CGFloat = 4
        static let s: CGFloat = 8
        static let m: CGFloat = 16
        static let l: CGFloat = 24
        static let xl: CGFloat = 32
    }

    static let cardRadius: CGFloat = 18
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
