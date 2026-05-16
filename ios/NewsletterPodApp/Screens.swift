import AuthenticationServices
import AVFoundation
import CoreLocation
import Speech
import StoreKit
import SwiftUI
import UIKit

struct RootView: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        Group {
            if viewModel.isAuthenticated {
                DashboardTabView()
                    .task {
                        try? await viewModel.refresh()
                        viewModel.evaluateOnboardingTrigger()
                    }
            } else {
                SignInView()
            }
        }
        .tint(Theme.Palette.amberDeep)
        .fullScreenCover(isPresented: $viewModel.showOnboarding) {
            OnboardingFlowView()
                .environmentObject(viewModel)
        }
        .overlay(alignment: .top) {
            VStack(spacing: 8) {
                if let errorMessage = viewModel.errorMessage {
                    Text(errorMessage)
                        .font(Theme.Typography.callout)
                        .foregroundStyle(.white)
                        .padding(10)
                        .background(Theme.Palette.amberDeep.opacity(0.95), in: Capsule())
                }
                if let savedMessage = viewModel.savedMessage {
                    Label(savedMessage, systemImage: "checkmark.circle.fill")
                        .font(Theme.Typography.calloutStrong)
                        .foregroundStyle(.white)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                        .background(Theme.Palette.amber, in: Capsule())
                        .shadow(color: Theme.Palette.cardShadow, radius: 6, y: 2)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
            }
            .padding(.top, 12)
            .animation(.spring(duration: 0.3), value: viewModel.savedMessage)
        }
    }
}

struct SignInView: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        ZStack {
            Theme.Palette.cream.ignoresSafeArea()

            VStack(alignment: .leading, spacing: Theme.Spacing.l) {
                Spacer()
                MetaLabel(text: "ClawCast")
                Text("Your daily\nbriefing, on tap.")
                    .font(Theme.Typography.display)
                    .foregroundStyle(Theme.Palette.ink)
                    .lineSpacing(2)
                Text("Pick your sources and format. We turn them into a private podcast you listen to in Apple Podcasts.")
                    .font(Theme.Typography.body)
                    .foregroundStyle(Theme.Palette.muted)

                SignInWithAppleButton(.signIn) { request in
                    request.requestedScopes = [.email, .fullName]
                } onCompletion: { result in
                    Task { await handleAppleSignIn(result: result) }
                }
                .signInWithAppleButtonStyle(.black)
                .frame(height: 52)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

                Spacer()
            }
            .padding(28)
        }
    }

    private func handleAppleSignIn(result: Result<ASAuthorization, Error>) async {
        guard case .success(let authorization) = result,
              let credential = authorization.credential as? ASAuthorizationAppleIDCredential,
              let tokenData = credential.identityToken,
              let token = String(data: tokenData, encoding: .utf8) else {
            viewModel.errorMessage = "Unable to read Apple identity token."
            return
        }
        let givenName = credential.fullName?.givenName?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        await viewModel.signIn(
            identityToken: token,
            givenName: (givenName?.isEmpty == false) ? givenName : nil
        )
    }
}

struct DashboardTabView: View {
    @EnvironmentObject private var viewModel: AppViewModel

    init() {
        let appearance = UITabBarAppearance()
        appearance.configureWithOpaqueBackground()
        appearance.backgroundColor = UIColor(Theme.Palette.cream)
        UITabBar.appearance().standardAppearance = appearance
        UITabBar.appearance().scrollEdgeAppearance = appearance
    }

    private var showsUpgradeTab: Bool {
        !viewModel.isPaid && viewModel.feed?.latestEpisode != nil
    }

    var body: some View {
        TabView(selection: $viewModel.selectedTab) {
            HomeView()
                .tabItem { Label("Home", systemImage: "house.fill") }
                .tag(DashboardTab.home)
            SourcesView()
                .tabItem { Label("Sources", systemImage: "tray.full") }
                .tag(DashboardTab.sources)
            PodcastSetupView()
                .tabItem { Label("Podcast", systemImage: "mic.fill") }
                .tag(DashboardTab.podcast)
            FeedAccessView()
                .tabItem { Label("Feed", systemImage: "antenna.radiowaves.left.and.right") }
                .tag(DashboardTab.feed)
            if showsUpgradeTab {
                PaywallView()
                    .tabItem { Label("Upgrade", systemImage: "sparkles") }
                    .tag(DashboardTab.upgrade)
            }
        }
    }
}

// MARK: - Home

struct HomeView: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @State private var isShowingSwipeDeck: Bool = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.Spacing.l) {
                    GreetingHeader()
                    if viewModel.isGenerating {
                        HomeGenerationBanner()
                    }
                    HeroEpisodeCard()
                    AboutPodcastCard()
                    SourcesSummaryCard()
                    TuneYourPodCard(isPresenting: $isShowingSwipeDeck)
                    LibraryEntryCard()
                    SetupChecklistCard()
                    FeedbackComposer()
                }
                .padding(.horizontal, Theme.Spacing.l)
                .padding(.top, Theme.Spacing.s)
                .padding(.bottom, Theme.Spacing.xl)
            }
            .navigationTitle("Your Briefing")
            .editorialBackground()
            .sheet(isPresented: $isShowingSwipeDeck) {
                SwipeDeckView()
                    .environmentObject(viewModel)
            }
        }
    }
}

/// Prominent top-of-home progress card that shows whenever a generation run
/// is active. Mirrors the alias step in the onboarding wizard so the user
/// sees the same chrome before AND after onboarding ends.
private struct HomeGenerationBanner: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        EditorialCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.s) {
                HStack(spacing: Theme.Spacing.m) {
                    Image(systemName: "wand.and.stars")
                        .foregroundStyle(Theme.Palette.amberDeep)
                        .font(.system(size: 22, weight: .semibold))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(headline)
                            .font(Theme.Typography.subtitle)
                            .foregroundStyle(Theme.Palette.ink)
                        Text("About 3–5 minutes. You can close the app — the episode will land in Apple Podcasts and on this screen when ready.")
                            .font(Theme.Typography.callout)
                            .foregroundStyle(Theme.Palette.inkSoft)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer(minLength: 0)
                }
                GenerationProgressBar(isGenerating: viewModel.isGenerating)
            }
        }
    }

    private var headline: String {
        viewModel.feed?.latestEpisode == nil
            ? "Your first episode is being made."
            : "We're putting together your next episode."
    }
}

private struct TuneYourPodCard: View {
    @Binding var isPresenting: Bool

    var body: some View {
        Button {
            isPresenting = true
        } label: {
            EditorialCard {
                HStack {
                    MetaLabel(text: "Tune your pod")
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(Theme.Palette.muted)
                }
                Text("Train the picker with a few quick swipes")
                    .font(Theme.Typography.subtitle)
                    .foregroundStyle(Theme.Palette.ink)
                Text("Swipe right on items you'd want to hear more about, left on the ones to skip. Your podcast learns from every card.")
                    .font(Theme.Typography.callout)
                    .foregroundStyle(Theme.Palette.inkSoft)
            }
        }
        .buttonStyle(.plain)
        .accessibilityHint("Opens the swipe deck to tune your pod")
    }
}

private struct LibraryEntryCard: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        NavigationLink {
            LibraryView()
                .environmentObject(viewModel)
        } label: {
            EditorialCard {
                HStack {
                    MetaLabel(text: "Episode library")
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(Theme.Palette.muted)
                }
                Text("Browse your past episodes")
                    .font(Theme.Typography.subtitle)
                    .foregroundStyle(Theme.Palette.ink)
                Text("Titles, sources, and transcripts for everything we've made for you. Open any episode in Apple Podcasts to listen.")
                    .font(Theme.Typography.callout)
                    .foregroundStyle(Theme.Palette.inkSoft)
            }
        }
        .buttonStyle(.plain)
        .accessibilityHint("Opens your episode library")
    }
}

private struct FeedbackComposer: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @StateObject private var dictation = FeedbackDictation()
    @State private var text: String = ""
    @State private var dictationStartLength: Int = 0
    @State private var isSubmitting = false
    @State private var lastSubmitSource: String = "text"
    @FocusState private var fieldFocused: Bool

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var canSubmit: Bool { !trimmed.isEmpty && !isSubmitting && !dictation.isRecording }

    var body: some View {
        EditorialCard {
            MetaLabel(text: "Send feedback")

            ZStack(alignment: .topLeading) {
                if text.isEmpty {
                    Text("What's working, what's not, what would you change?")
                        .font(Theme.Typography.callout)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 5)
                        .padding(.vertical, 8)
                }
                TextEditor(text: $text)
                    .scrollContentBackground(.hidden)
                    .frame(minHeight: 120)
                    .focused($fieldFocused)
            }
            .background(Theme.Palette.cream.opacity(0.6), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(Theme.Palette.rule, lineWidth: 1)
            )

            if let error = dictation.errorMessage {
                Text(error)
                    .font(Theme.Typography.callout)
                    .foregroundStyle(.red)
            }

            HStack(spacing: 12) {
                Button {
                    Task { await toggleDictation() }
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: dictation.isRecording ? "stop.circle.fill" : "mic.fill")
                        Text(dictation.isRecording ? "Stop" : "Dictate")
                    }
                    .font(Theme.Typography.calloutStrong)
                }
                .buttonStyle(.amberOutlined)
                .disabled(isSubmitting)

                Spacer()

                Button {
                    Task { await submit() }
                } label: {
                    if isSubmitting {
                        ProgressView()
                    } else {
                        Text("Submit")
                    }
                }
                .buttonStyle(.amberFilled)
                .disabled(!canSubmit)
            }
        }
        .onChange(of: dictation.transcript) { _, newValue in
            applyDictationUpdate(newValue)
        }
        .onDisappear { dictation.cancel() }
    }

    private func toggleDictation() async {
        if dictation.isRecording {
            dictation.stop()
            lastSubmitSource = "voice"
        } else {
            fieldFocused = false
            dictationStartLength = text.count
            lastSubmitSource = "voice"
            await dictation.start()
        }
    }

    private func applyDictationUpdate(_ partial: String) {
        let prefix = String(text.prefix(dictationStartLength))
        let separator = (prefix.isEmpty || prefix.hasSuffix(" ") || prefix.hasSuffix("\n")) ? "" : " "
        text = prefix + separator + partial
    }

    private func submit() async {
        guard canSubmit else { return }
        isSubmitting = true
        fieldFocused = false
        defer { isSubmitting = false }
        let ok = await viewModel.submitFeedback(text: trimmed, source: lastSubmitSource)
        if ok {
            text = ""
            dictation.reset()
            dictationStartLength = 0
            lastSubmitSource = "text"
        }
    }
}

private struct GreetingHeader: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        Text(greeting)
            .font(Theme.Typography.display)
            .foregroundStyle(Theme.Palette.ink)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityAddTraits(.isHeader)
    }

    private var greeting: String {
        guard let user = viewModel.user, user.hasFriendlyName else {
            return "Good \(timeOfDay)."
        }
        return "Good \(timeOfDay), \(user.firstName)."
    }

    private var timeOfDay: String {
        var calendar = Calendar.current
        if let identifier = viewModel.user?.timezone,
           let timeZone = TimeZone(identifier: identifier) {
            calendar.timeZone = timeZone
        }
        let hour = calendar.component(.hour, from: Date())
        switch hour {
        case 5..<12: return "morning"
        case 12..<17: return "afternoon"
        case 17..<22: return "evening"
        default: return "night"
        }
    }
}

private struct HeroEpisodeCard: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @State private var isDescriptionExpanded = false

    var body: some View {
        EditorialCard {
            MetaLabel(text: episodeBadge)
            Text(episodeTitle)
                .font(Theme.Typography.title)
                .foregroundStyle(Theme.Palette.ink)
                .fixedSize(horizontal: false, vertical: true)

            if let latest = viewModel.feed?.latestEpisode {
                CollapsibleDescription(text: latest.description, isExpanded: $isDescriptionExpanded)

                HStack(spacing: Theme.Spacing.m) {
                    if let duration = latest.durationSeconds {
                        Label(formatDuration(duration), systemImage: "clock")
                    }
                    Label("\(latest.processedItemCount) items", systemImage: "doc.text")
                    Label(
                        HeroEpisodeCard.relativeDate.localizedString(for: latest.publishedAt, relativeTo: Date()),
                        systemImage: "calendar"
                    )
                }
                .font(Theme.Typography.callout)
                .foregroundStyle(Theme.Palette.muted)

                if let transcript = latest.transcriptText, !transcript.isEmpty {
                    CollapsibleTranscript(text: transcript)
                }
            } else if viewModel.selectedSources.isEmpty {
                Text("Tap below for a guided setup — pick sources, choose a format, and we'll start your first episode.")
                    .font(Theme.Typography.body)
                    .foregroundStyle(Theme.Palette.inkSoft)

                Button {
                    viewModel.resumeOnboarding()
                } label: {
                    Label("Start guided setup", systemImage: "wand.and.stars")
                }
                .buttonStyle(.amberFilled)
            } else if !viewModel.isGenerating {
                Text("Your sources are set. Tap Generate below to make your first episode now, or wait for your scheduled delivery.")
                    .font(Theme.Typography.body)
                    .foregroundStyle(Theme.Palette.inkSoft)
            }

            EditorialDivider()

            VStack(spacing: Theme.Spacing.s) {
                Button {
                    openInApplePodcasts()
                } label: {
                    Label("Open in Apple Podcasts", systemImage: "play.fill")
                }
                .buttonStyle(.amberFilled)
                .disabled(viewModel.feed?.feedURL == nil)

                Button {
                    Task { await viewModel.generateNow() }
                } label: {
                    if viewModel.isGenerating {
                        HStack(spacing: 8) {
                            ProgressView().tint(Theme.Palette.amberDeep)
                            Text("Generating… (you can leave the app)")
                        }
                    } else {
                        Label("Generate episode now", systemImage: "wand.and.stars")
                    }
                }
                .buttonStyle(.amberOutlined)
                .disabled(viewModel.isGenerating || viewModel.selectedSources.isEmpty)
            }
        }
    }

    private var episodeBadge: String {
        if viewModel.feed?.latestEpisode != nil { return "Latest Episode" }
        if viewModel.isGenerating { return "Generating Now" }
        return "Coming Soon"
    }

    private var episodeTitle: String {
        if let title = viewModel.feed?.latestEpisode?.title { return title }
        if viewModel.isGenerating { return "Cooking up your first briefing…" }
        return "No episode yet"
    }

    private func formatDuration(_ seconds: Int) -> String {
        let minutes = max(1, Int((Double(seconds) / 60.0).rounded()))
        return "\(minutes) min"
    }

    /// "5 minutes ago", "2 days ago" — matches the casual feel of the rest
    /// of the meta row. unitsStyle .full over .abbreviated for legibility.
    static let relativeDate: RelativeDateTimeFormatter = {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .full
        return formatter
    }()

    private func openInApplePodcasts() {
        guard let urlString = viewModel.feed?.feedURL,
              let url = URL(string: urlString),
              let host = url.host else { return }
        var components = URLComponents()
        components.scheme = "podcast"
        components.host = host
        components.path = url.path
        if let podcastURL = components.url {
            UIApplication.shared.open(podcastURL) { ok in
                if !ok { UIApplication.shared.open(url) }
            }
        }
    }
}

private struct CollapsibleDescription: View {
    let text: String
    @Binding var isExpanded: Bool

    private let collapsedRowLimit = 5

    private var blocks: [DescriptionBlock] {
        DescriptionBlock.parse(text)
    }

    private var visibleBlocks: [DescriptionBlock] {
        if isExpanded { return blocks }
        return Array(blocks.prefix(collapsedRowLimit))
    }

    private var canExpand: Bool {
        blocks.count > collapsedRowLimit
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.s) {
            ForEach(Array(visibleBlocks.enumerated()), id: \.offset) { _, block in
                row(for: block)
            }

            if canExpand {
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) { isExpanded.toggle() }
                } label: {
                    HStack(spacing: 4) {
                        Text(isExpanded ? "Show less" : "Show more")
                        Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                            .font(.system(size: 11, weight: .semibold))
                    }
                    .font(Theme.Typography.calloutStrong)
                    .foregroundStyle(Theme.Palette.amberDeep)
                }
                .buttonStyle(.plain)
                .padding(.top, 2)
            }
        }
    }

    @ViewBuilder
    private func row(for block: DescriptionBlock) -> some View {
        switch block {
        case .heading(let inline):
            Text(formatted(inline))
                .font(Theme.Typography.subtitle)
                .foregroundStyle(Theme.Palette.ink)
                .padding(.top, 4)
        case .bullet(let inline):
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("•")
                    .font(Theme.Typography.bodyStrong)
                    .foregroundStyle(Theme.Palette.amber)
                Text(formatted(inline))
                    .font(Theme.Typography.body)
                    .foregroundStyle(Theme.Palette.inkSoft)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        case .paragraph(let inline):
            Text(formatted(inline))
                .font(Theme.Typography.body)
                .foregroundStyle(Theme.Palette.inkSoft)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func formatted(_ inline: String) -> AttributedString {
        let options = AttributedString.MarkdownParsingOptions(
            interpretedSyntax: .inlineOnlyPreservingWhitespace
        )
        guard var attributed = try? AttributedString(markdown: inline, options: options) else {
            return AttributedString(inline)
        }
        for run in attributed.runs where run.link != nil {
            attributed[run.range].foregroundColor = Theme.Palette.amberDeep
            attributed[run.range].underlineStyle = .single
        }
        return attributed
    }
}

private struct CollapsibleTranscript: View {
    let text: String
    @State private var isExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.s) {
            Button {
                withAnimation(.easeInOut(duration: 0.2)) { isExpanded.toggle() }
            } label: {
                HStack {
                    Text("Transcript")
                        .font(Theme.Typography.calloutStrong)
                        .foregroundStyle(Theme.Palette.amberDeep)
                    Spacer()
                    Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(Theme.Palette.amberDeep)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if isExpanded {
                Text(text)
                    .font(Theme.Typography.callout)
                    .foregroundStyle(Theme.Palette.inkSoft)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
        }
    }
}

private enum DescriptionBlock {
    case heading(String)
    case bullet(String)
    case paragraph(String)

    static func parse(_ text: String) -> [DescriptionBlock] {
        var blocks: [DescriptionBlock] = []
        for raw in text.components(separatedBy: "\n") {
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.isEmpty { continue }
            if let bullet = stripBullet(line) {
                blocks.append(.bullet(bullet))
            } else if isHeadingOnly(line) {
                blocks.append(.heading(stripHeading(line)))
            } else {
                blocks.append(.paragraph(line))
            }
        }
        return blocks
    }

    private static func stripBullet(_ line: String) -> String? {
        if line.hasPrefix("- ") { return String(line.dropFirst(2)) }
        if line.hasPrefix("* ") { return String(line.dropFirst(2)) }
        return nil
    }

    private static func isHeadingOnly(_ line: String) -> Bool {
        line.hasPrefix("**") && line.hasSuffix("**") && line.count >= 4 &&
            !line.dropFirst(2).dropLast(2).contains("**")
    }

    private static func stripHeading(_ line: String) -> String {
        String(line.dropFirst(2).dropLast(2))
    }
}

private struct AboutPodcastCard: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        Button {
            viewModel.selectedTab = .podcast
        } label: {
            EditorialCard {
                HStack {
                    MetaLabel(text: "About this podcast")
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(Theme.Palette.muted)
                }
                Text(viewModel.profile?.title ?? "ClawCast")
                    .font(Theme.Typography.title)
                    .foregroundStyle(Theme.Palette.ink)

                VStack(alignment: .leading, spacing: Theme.Spacing.s) {
                    infoRow(label: "Format", value: formatLabel)
                    infoRow(label: "Hosts", value: hostsLabel)
                    infoRow(label: "Length", value: "\(viewModel.profile?.desiredDurationMinutes ?? 8) min")
                    infoRow(label: "Delivery", value: deliveryLabel)
                }
            }
        }
        .buttonStyle(.plain)
    }

    private var formatLabel: String {
        switch viewModel.profile?.formatPreset {
        case "solo_host": return "Solo host"
        case "two_hosts": return "Two hosts"
        case "rotating_guest": return "Rotating guest"
        default: return "Two hosts"
        }
    }

    private var hostsLabel: String {
        let primary = voiceName(for: viewModel.profile?.voiceID)
        switch viewModel.profile?.formatPreset {
        case "two_hosts":
            let secondary = voiceName(for: viewModel.profile?.secondaryVoiceID)
            return "\(primary) & \(secondary)"
        case "rotating_guest":
            return "\(primary) & rotating guest"
        default:
            return primary
        }
    }

    private var deliveryLabel: String {
        let days = viewModel.schedule?.weekdays.map { $0.prefix(3).capitalized }.joined(separator: ", ")
        return days?.isEmpty == false ? days! : "Not set"
    }

    private func voiceName(for voiceID: String?) -> String {
        if let id = voiceID {
            if let catalog = viewModel.catalogVoices.first(where: { $0.id == id }) {
                return catalog.name
            }
            if let fallback = PodcastSetupView.voiceOptions.first(where: { $0.id == id }) {
                return fallback.name
            }
        }
        return PodcastSetupView.voiceOptions[0].name
    }

    private func infoRow(label: String, value: String) -> some View {
        HStack {
            Text(label)
                .font(Theme.Typography.callout)
                .foregroundStyle(Theme.Palette.muted)
            Spacer()
            Text(value)
                .font(Theme.Typography.calloutStrong)
                .foregroundStyle(Theme.Palette.ink)
        }
    }
}

private struct SourcesSummaryCard: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        Button {
            viewModel.selectedTab = .sources
        } label: {
            EditorialCard {
                HStack {
                    MetaLabel(text: "Your sources")
                    Spacer()
                    Text("\(viewModel.selectedSources.count)")
                        .font(Theme.Typography.meta)
                        .foregroundStyle(Theme.Palette.muted)
                    Image(systemName: "chevron.right")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(Theme.Palette.muted)
                }

                if viewModel.selectedSources.isEmpty {
                    Text("Pick at least one source on the Sources tab to start receiving episodes.")
                        .font(Theme.Typography.body)
                        .foregroundStyle(Theme.Palette.inkSoft)
                } else {
                    VStack(alignment: .leading, spacing: Theme.Spacing.s) {
                        ForEach(viewModel.selectedSources.prefix(4)) { source in
                            HStack(spacing: Theme.Spacing.s) {
                                Circle()
                                    .fill(Theme.Palette.amber)
                                    .frame(width: 6, height: 6)
                                Text(source.name)
                                    .font(Theme.Typography.body)
                                    .foregroundStyle(Theme.Palette.ink)
                                    .lineLimit(1)
                                Spacer()
                                if source.isCustom {
                                    Text("Custom")
                                        .font(Theme.Typography.meta)
                                        .foregroundStyle(Theme.Palette.muted)
                                }
                            }
                        }
                        if viewModel.selectedSources.count > 4 {
                            Text("+\(viewModel.selectedSources.count - 4) more")
                                .font(Theme.Typography.callout)
                                .foregroundStyle(Theme.Palette.muted)
                        }
                    }
                }
            }
        }
        .buttonStyle(.plain)
        .accessibilityHint("Opens the Sources tab")
    }
}

private struct SetupChecklistCard: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        if allComplete { EmptyView() } else {
            EditorialCard {
                MetaLabel(text: "Setup checklist")
                VStack(alignment: .leading, spacing: Theme.Spacing.s) {
                    Button {
                        viewModel.selectedTab = .sources
                    } label: {
                        ChecklistRow(label: "Pick at least one source", isComplete: hasSources)
                    }
                    .buttonStyle(.plain)

                    Button {
                        viewModel.selectedTab = .podcast
                    } label: {
                        ChecklistRow(label: "Configure your show", isComplete: hasShowConfigured)
                    }
                    .buttonStyle(.plain)

                    Button {
                        viewModel.selectedTab = .podcast
                    } label: {
                        ChecklistRow(label: "Set a delivery schedule", isComplete: hasSchedule)
                    }
                    .buttonStyle(.plain)

                    Button {
                        Task { await viewModel.generateNow() }
                    } label: {
                        ChecklistRow(label: "First episode ready", isComplete: hasEpisode)
                    }
                    .buttonStyle(.plain)
                    .disabled(!hasSources || hasEpisode)
                }

                Button {
                    viewModel.resumeOnboarding()
                } label: {
                    Label("Resume guided setup", systemImage: "wand.and.stars")
                }
                .buttonStyle(.amberOutlined)
            }
        }
    }

    private var hasSources: Bool { !viewModel.selectedSources.isEmpty }
    private var hasShowConfigured: Bool { (viewModel.profile?.title.isEmpty == false) }
    private var hasSchedule: Bool { (viewModel.schedule?.weekdays.isEmpty == false) }
    private var hasEpisode: Bool { viewModel.feed?.latestEpisode != nil }
    private var allComplete: Bool { hasSources && hasShowConfigured && hasSchedule && hasEpisode }
}

// MARK: - Sources

struct SourcesView: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @State private var selectedCatalogIDs: Set<String> = []
    @State private var customURLs: [String] = [""]
    @State private var isShowingAddSubstack = false

    private struct TopicGroup: Identifiable {
        let name: String
        let icon: String
        let sources: [CatalogSourceDTO]
        var id: String { name }
    }

    private var catalogTopicGroups: [TopicGroup] {
        var topicOrder: [String] = []
        var bucket: [String: [CatalogSourceDTO]] = [:]
        for source in viewModel.catalogSources {
            let topic = (source.topic?.isEmpty == false) ? source.topic! : "Other"
            if bucket[topic] == nil {
                topicOrder.append(topic)
                bucket[topic] = []
            }
            bucket[topic]?.append(source)
        }
        return topicOrder.map { topic in
            TopicGroup(
                name: topic,
                icon: OnboardingStarterPack.icon(forTopic: topic),
                sources: bucket[topic] ?? []
            )
        }
    }

    private func selectedCount(in sources: [CatalogSourceDTO]) -> Int {
        sources.reduce(0) { $0 + (selectedCatalogIDs.contains($1.sourceID) ? 1 : 0) }
    }

    private func autosaveSources() {
        let catalogIDs = Array(selectedCatalogIDs)
        let urls = customURLs
        Task {
            await viewModel.saveSources(catalogIDs: catalogIDs, customURLs: urls)
        }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    NewsletterEmailCard()
                }
                .listRowInsets(EdgeInsets(top: 12, leading: 0, bottom: 12, trailing: 0))
                .listRowBackground(Color.clear)

                if let address = viewModel.user?.inboundAddress, !address.isEmpty {
                    Section("Your Substacks") {
                        SubstackSubscriptionsList(isShowingAddSheet: $isShowingAddSubstack)
                    }

                    Section("Recent Newsletters") {
                        InboundItemsList()
                    }
                }

                Section("Catalog Sources") {
                    ForEach(catalogTopicGroups) { group in
                        DisclosureGroup {
                            ForEach(group.sources) { source in
                                Toggle(source.name, isOn: Binding(
                                    get: { selectedCatalogIDs.contains(source.sourceID) },
                                    set: { isSelected in
                                        if isSelected {
                                            selectedCatalogIDs.insert(source.sourceID)
                                        } else {
                                            selectedCatalogIDs.remove(source.sourceID)
                                        }
                                        autosaveSources()
                                    }
                                ))
                            }
                        } label: {
                            HStack(spacing: Theme.Spacing.s) {
                                Image(systemName: group.icon)
                                    .foregroundStyle(Theme.Palette.amberDeep)
                                    .frame(width: 22)
                                Text(group.name)
                                Spacer()
                                Text("\(selectedCount(in: group.sources)) of \(group.sources.count)")
                                    .font(Theme.Typography.meta)
                                    .foregroundStyle(.secondary)
                                    .monospacedDigit()
                            }
                        }
                    }
                }

                Section("Custom RSS") {
                    ForEach(customURLs.indices, id: \.self) { index in
                        TextField("https://example.com/feed.xml", text: $customURLs[index])
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                            .onSubmit { autosaveSources() }
                    }

                    Button("Add another feed") {
                        customURLs.append("")
                    }
                }
            }
            .navigationTitle("Sources")
            .editorialBackground()
            .refreshable {
                async let inbound: Void = viewModel.loadInboundItems()
                async let intents: Void = viewModel.loadSubstackIntents()
                _ = await (inbound, intents)
            }
            .task {
                async let inbound: Void = viewModel.loadInboundItems()
                async let intents: Void = viewModel.loadSubstackIntents()
                _ = await (inbound, intents)
            }
            .sheet(isPresented: $isShowingAddSubstack) {
                AddSubstackSheet()
                    .environmentObject(viewModel)
            }
            .onAppear {
                selectedCatalogIDs = Set(
                    viewModel.selectedSources
                        .filter { !$0.isCustom }
                        .map(\.sourceID)
                )
                let custom = viewModel.selectedSources
                    .filter(\.isCustom)
                    .map(\.rssURL)
                customURLs = custom.isEmpty ? [""] : custom
            }
        }
    }
}

private struct NewsletterEmailCard: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @State private var didCopy = false

    var body: some View {
        EditorialCard {
            HStack(spacing: Theme.Spacing.s) {
                MetaLabel(text: "Newsletter Email")
                Spacer()
                if didCopy {
                    Label("Copied", systemImage: "checkmark.circle.fill")
                        .font(Theme.Typography.meta)
                        .foregroundStyle(Theme.Palette.amberDeep)
                        .transition(.opacity)
                }
            }

            if let address = viewModel.user?.inboundAddress, !address.isEmpty {
                Text(address)
                    .font(.system(size: 17, weight: .semibold, design: .monospaced))
                    .foregroundStyle(Theme.Palette.ink)
                    .textSelection(.enabled)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)

                Text("Use this address to subscribe to any newsletter (Substack, Beehiiv, Stratechery…). New issues land here and we mix them into your next episode.")
                    .font(Theme.Typography.callout)
                    .foregroundStyle(Theme.Palette.muted)

                Button {
                    UIPasteboard.general.string = address
                    withAnimation { didCopy = true }
                    Task { @MainActor in
                        try? await Task.sleep(nanoseconds: 1_500_000_000)
                        withAnimation { didCopy = false }
                    }
                } label: {
                    Label("Copy address", systemImage: "doc.on.doc")
                }
                .buttonStyle(.amberFilled)
            } else {
                Text("Generating your private address…")
                    .font(Theme.Typography.callout)
                    .foregroundStyle(Theme.Palette.muted)
            }
        }
        .padding(.horizontal, Theme.Spacing.m)
    }
}

private struct InboundItemsList: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        if viewModel.inboundItems.isEmpty {
            HStack(spacing: Theme.Spacing.s) {
                Image(systemName: "tray")
                    .foregroundStyle(Theme.Palette.muted)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Nothing yet")
                        .font(Theme.Typography.body)
                        .foregroundStyle(Theme.Palette.ink)
                    Text("Forwarded newsletters will appear here within seconds of arriving.")
                        .font(Theme.Typography.callout)
                        .foregroundStyle(Theme.Palette.muted)
                }
            }
            .padding(.vertical, 4)
        } else {
            ForEach(viewModel.inboundItems) { item in
                InboundItemRow(item: item)
            }
        }
    }
}

private struct InboundItemRow: View {
    let item: InboundItemDTO

    private static let timestampFormatter: RelativeDateTimeFormatter = {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated
        return formatter
    }()

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(item.subject)
                .font(Theme.Typography.bodyStrong)
                .foregroundStyle(Theme.Palette.ink)
                .lineLimit(2)
            HStack(spacing: 6) {
                Text(item.displaySender)
                    .lineLimit(1)
                Text("·")
                Text(Self.timestampFormatter.localizedString(for: item.receivedAt, relativeTo: Date()))
            }
            .font(Theme.Typography.callout)
            .foregroundStyle(Theme.Palette.muted)
        }
        .padding(.vertical, 4)
    }
}

// MARK: - Substack subscriptions

struct SubstackSubscriptionsList: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @Binding var isShowingAddSheet: Bool

    var body: some View {
        Group {
            if viewModel.substackIntents.isEmpty {
                HStack(spacing: Theme.Spacing.s) {
                    Image(systemName: "envelope.badge")
                        .foregroundStyle(Theme.Palette.muted)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("No Substacks yet")
                            .font(Theme.Typography.body)
                            .foregroundStyle(.primary)
                        Text("Tap below to subscribe to a Substack with your ClawCast address.")
                            .font(Theme.Typography.callout)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 4)
            } else {
                ForEach(viewModel.substackIntents) { intent in
                    SubstackSubscriptionRow(intent: intent)
                        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                            Button(role: .destructive) {
                                Task { await viewModel.deleteSubstackIntent(intent) }
                            } label: {
                                Label("Remove", systemImage: "trash")
                            }
                        }
                }
            }

            Button {
                isShowingAddSheet = true
            } label: {
                Label("Add a Substack", systemImage: "plus.circle.fill")
                    .font(Theme.Typography.body)
                    .foregroundStyle(Theme.Palette.amberDeep)
            }
            .padding(.vertical, 4)
        }
    }
}

private struct SubstackSubscriptionRow: View {
    let intent: SubstackIntentDTO

    private static let timestampFormatter: RelativeDateTimeFormatter = {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated
        return formatter
    }()

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Text(intent.displayTitle)
                    .font(Theme.Typography.bodyStrong)
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                Spacer(minLength: Theme.Spacing.s)
                statusBadge
            }
            statusDetail
                .font(Theme.Typography.callout)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }

    @ViewBuilder
    private var statusBadge: some View {
        switch intent.displayStatus {
        case .confirmed:
            Label("Confirmed", systemImage: "checkmark.circle.fill")
                .labelStyle(.iconOnly)
                .foregroundStyle(.green)
                .imageScale(.medium)
                .accessibilityLabel("Confirmed")
        default:
            Image(systemName: "hourglass")
                .foregroundStyle(Theme.Palette.amberDeep)
                .imageScale(.medium)
                .accessibilityLabel("Pending")
        }
    }

    @ViewBuilder
    private var statusDetail: some View {
        switch intent.displayStatus {
        case .confirmed:
            if let confirmedAt = intent.confirmedAt {
                Text("Confirmed " + Self.timestampFormatter.localizedString(for: confirmedAt, relativeTo: Date()))
            } else {
                Text("Confirmed")
            }
        default:
            // Per product decision: keep this as pending until a real post
            // arrives, with copy that sets the expectation it may take days
            // for low-volume publications.
            Text("Pending — waiting for the first post. Low-volume Substacks can take a few days.")
        }
    }
}

struct AddSubstackSheet: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL

    @State private var input: String = ""
    @State private var preview: SubstackProbeDTO?
    @State private var isProbing = false
    @State private var probeError: String?
    @State private var hasContinued = false
    @State private var probeTask: Task<Void, Never>?
    @State private var copiedNotice: String?
    @State private var copiedNoticeTask: Task<Void, Never>?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    VStack(alignment: .leading, spacing: Theme.Spacing.s) {
                        instructionStep(number: 1, text: "Paste a Substack URL or @handle below.")
                        instructionStep(number: 2, text: "Tap Continue on Substack — we'll copy your ClawCast email to your clipboard and open the publication in Safari.")
                        instructionStep(number: 3, text: "On Substack, paste your ClawCast email (not your personal one) and subscribe. We auto-confirm the double opt-in for you.")
                        instructionStep(number: 4, text: "New free posts arrive in ClawCast as part of your podcast — your personal inbox stays clean.")
                    }
                    .padding(.vertical, Theme.Spacing.xs)
                } header: {
                    Text("How it works")
                }

                Section {
                    TextField("e.g. heathercoxrichardson.substack.com", text: $input)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                        .submitLabel(.done)
                        .onSubmit { triggerProbe() }
                        .onChange(of: input) { _, _ in scheduleProbe() }
                } header: {
                    Text("Substack URL or handle")
                } footer: {
                    if let probeError {
                        Text(probeError)
                            .foregroundStyle(.red)
                    } else {
                        Text("Paste a URL like `lenny.substack.com` or `@lenny`.")
                    }
                }

                if let preview {
                    Section("Publication") {
                        SubstackPreviewCard(preview: preview)
                    }

                    if preview.hasPaidTier {
                        Section {
                            Label {
                                Text("Free posts will arrive at your ClawCast address. Paid posts won't — those go to whatever email is on your Substack account.")
                                    .font(Theme.Typography.callout)
                            } icon: {
                                Image(systemName: "exclamationmark.triangle.fill")
                                    .foregroundStyle(Theme.Palette.amberDeep)
                            }
                        }
                    }

                    Section {
                        Label {
                            Text("Substack may prefill your email — make sure to paste your ClawCast address. We'll copy it to your clipboard when you continue.")
                                .font(Theme.Typography.callout)
                                .foregroundStyle(.secondary)
                        } icon: {
                            Image(systemName: "doc.on.doc")
                                .foregroundStyle(Theme.Palette.muted)
                        }
                    }
                } else if isProbing {
                    Section {
                        HStack(spacing: Theme.Spacing.s) {
                            ProgressView()
                            Text("Looking up that Substack…")
                                .font(Theme.Typography.callout)
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                if hasContinued {
                    Section {
                        Label {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("We'll show this as Pending until the first post lands at your alias.")
                                Text("This doesn't affect any subscription at your personal inbox.")
                            }
                            .font(Theme.Typography.callout)
                            .foregroundStyle(.secondary)
                        } icon: {
                            Image(systemName: "info.circle")
                                .foregroundStyle(Theme.Palette.amberDeep)
                        }
                    }
                }
            }
            .navigationTitle("Add a Substack")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .safeAreaInset(edge: .bottom) {
                continueButton
                    .padding(.horizontal, Theme.Spacing.m)
                    .padding(.bottom, Theme.Spacing.m)
                    .background(.thinMaterial)
            }
            .overlay(alignment: .top) {
                if let copiedNotice {
                    Label(copiedNotice, systemImage: "doc.on.doc.fill")
                        .font(Theme.Typography.calloutStrong)
                        .foregroundStyle(.white)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                        .background(Theme.Palette.amber, in: Capsule())
                        .shadow(color: Theme.Palette.cardShadow, radius: 6, y: 2)
                        .padding(.top, Theme.Spacing.s)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
            }
            .animation(.spring(duration: 0.3), value: copiedNotice)
        }
        .onDisappear {
            probeTask?.cancel()
            copiedNoticeTask?.cancel()
        }
    }

    @ViewBuilder
    private func instructionStep(number: Int, text: String) -> some View {
        HStack(alignment: .top, spacing: Theme.Spacing.s) {
            Text("\(number)")
                .font(Theme.Typography.calloutStrong)
                .foregroundStyle(.white)
                .frame(width: 22, height: 22)
                .background(Theme.Palette.amber, in: Circle())
            Text(text)
                .font(Theme.Typography.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    @ViewBuilder
    private var continueButton: some View {
        Button {
            Task { await handleContinue() }
        } label: {
            HStack {
                Spacer()
                if hasContinued {
                    Label("Subscribed — open Substack again", systemImage: "arrow.up.right.square")
                } else {
                    Label("Continue on Substack", systemImage: "arrow.up.right.square")
                }
                Spacer()
            }
            .frame(minHeight: 44)
        }
        .buttonStyle(.amberFilled)
        .disabled(preview == nil)
    }

    private func scheduleProbe() {
        probeTask?.cancel()
        preview = nil
        probeError = nil
        hasContinued = false
        let trimmed = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count > 3 else { return }
        probeTask = Task {
            // Debounce so we don't fire a probe on every keystroke.
            try? await Task.sleep(nanoseconds: 350_000_000)
            if Task.isCancelled { return }
            await runProbe()
        }
    }

    private func triggerProbe() {
        probeTask?.cancel()
        Task { await runProbe() }
    }

    @MainActor
    private func runProbe() async {
        isProbing = true
        defer { isProbing = false }
        let result = await viewModel.probeSubstack(url: input)
        if let result {
            preview = result
            probeError = nil
        } else {
            preview = nil
            probeError = viewModel.errorMessage ?? "Could not reach that Substack."
        }
    }

    @MainActor
    private func handleContinue() async {
        guard let preview else { return }
        guard let intent = await viewModel.createSubstackIntent(pubURL: preview.pubURL) else { return }
        // Stash the alias in the clipboard so the user can paste it into
        // Substack's subscribe form in Safari.
        UIPasteboard.general.string = intent.aliasEmail
        showCopiedNotice("ClawCast email copied")
        // Brief pause so the toast animates in before Safari takes over the
        // screen — otherwise the user only sees it on their way back.
        try? await Task.sleep(nanoseconds: 350_000_000)
        if let url = intent.subscribeURL {
            openURL(url)
        }
        hasContinued = true
    }

    private func showCopiedNotice(_ message: String) {
        copiedNoticeTask?.cancel()
        copiedNotice = message
        copiedNoticeTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            if Task.isCancelled { return }
            copiedNotice = nil
        }
    }
}

private struct SubstackPreviewCard: View {
    let preview: SubstackProbeDTO

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(preview.title ?? preview.pubHost)
                .font(Theme.Typography.bodyStrong)
                .foregroundStyle(.primary)
                .lineLimit(2)
            if let author = preview.author, !author.isEmpty {
                Text(author)
                    .font(Theme.Typography.callout)
                    .foregroundStyle(.secondary)
            }
            HStack(spacing: Theme.Spacing.s) {
                Text(preview.pubHost)
                    .font(Theme.Typography.meta)
                    .foregroundStyle(.secondary)
                if preview.hasPaidTier {
                    Text("Paid tier")
                        .font(Theme.Typography.meta)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(
                            RoundedRectangle(cornerRadius: 4)
                                .fill(Theme.Palette.amber.opacity(0.2))
                        )
                        .foregroundStyle(Theme.Palette.amberDeep)
                }
            }
        }
        .padding(.vertical, 4)
    }
}

// MARK: - Podcast setup

struct GuidancePreset: Identifiable, Hashable {
    let id: String
    let label: String
    let tone: String
    let humorStyle: String
    let keyFindingsCount: Int
    let personalizedGreeting: Bool
    let guidance: String
}

struct PodcastSetupView: View {
    static let voiceOptions: [(id: String, name: String)] = [
        ("suMMgpGbVcnihP1CcgFS", "Vinnie Chase"),
        ("RKCbSROXui75bk1SVpy8", "Demi Dreams"),
    ]

    static let toneOptions: [(id: String, label: String)] = [
        ("calm_analyst", "Calm analyst"),
        ("warm_friendly", "Warm & friendly"),
        ("snappy_news", "Snappy news"),
        ("playful", "Playful"),
    ]

    static let humorOptions: [(id: String, label: String)] = [
        ("none", "None"),
        ("dry_wit", "Dry wit"),
        ("dad_jokes", "Dad jokes"),
    ]

    static let guidancePresets: [GuidancePreset] = [
        GuidancePreset(
            id: "quick_calm",
            label: "Quick & Calm",
            tone: "calm_analyst",
            humorStyle: "none",
            keyFindingsCount: 3,
            personalizedGreeting: true,
            guidance: "Prioritize clarity over color."
        ),
        GuidancePreset(
            id: "morning_energy",
            label: "Morning Energy",
            tone: "warm_friendly",
            humorStyle: "dad_jokes",
            keyFindingsCount: 5,
            personalizedGreeting: true,
            guidance: "Open with a warm greeting and one upbeat sentence about the day."
        ),
        GuidancePreset(
            id: "newsroom_brief",
            label: "Newsroom Brief",
            tone: "snappy_news",
            humorStyle: "none",
            keyFindingsCount: 5,
            personalizedGreeting: false,
            guidance: "Tight transitions, lead with the lede, no filler."
        ),
        GuidancePreset(
            id: "friend_catching_up",
            label: "Friend Catching You Up",
            tone: "warm_friendly",
            humorStyle: "dry_wit",
            keyFindingsCount: 3,
            personalizedGreeting: true,
            guidance: "Sound like a smart friend explaining over coffee. Use 'you' often."
        ),
    ]

    static let guidanceMaxLength = 500

    @EnvironmentObject private var viewModel: AppViewModel
    @State private var displayName = ""
    @State private var formatPreset = "two_hosts"
    @State private var durationMinutes: Int = 3
    private static let durationOptions: [Int] = [3, 4, 5]

    /// Snap a stored duration onto the discrete {3, 4, 5} picker. Handles
    /// legacy profiles that were saved at 6+ minutes via the old slider.
    private static func clampDuration(_ value: Int) -> Int {
        if value <= 3 { return 3 }
        if value >= 5 { return 5 }
        return 4
    }
    @State private var voiceID: String = PodcastSetupView.voiceOptions[0].id
    @State private var secondaryVoiceID: String = PodcastSetupView.voiceOptions[1].id
    @State private var tone: String = "calm_analyst"
    @State private var humorStyle: String = "none"
    @State private var keyFindingsCount: Int = 3
    @State private var personalizedGreeting: Bool = true
    @State private var includeTopTakeaways: Bool = true
    @State private var includeWeather: Bool = false
    @State private var weatherLocation: String = ""
    @State private var customGuidance: String = ""
    @State private var customGuidancePresetID: String? = nil
    @StateObject private var samplePlayer = VoiceSamplePlayer()
    @StateObject private var locationResolver = LocationResolver()
    @State private var didLoadInitialState = false
    @State private var isApplyingPreset = false
    @State private var nameSaveTask: Task<Void, Never>?
    @State private var configSaveTask: Task<Void, Never>?

    /// Full voice catalog with the legacy 2-voice list as fallback when the
    /// server catalog hasn't loaded yet. Mirrors `OnboardingVoicesStep`.
    private var voices: [CatalogVoiceDTO] {
        if !viewModel.catalogVoices.isEmpty { return viewModel.catalogVoices }
        return PodcastSetupView.voiceOptions.map {
            CatalogVoiceDTO(id: $0.id, name: $0.name, gender: "neutral", description: "", previewURL: nil)
        }
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("You") {
                    TextField("First name", text: $displayName)
                        .textContentType(.givenName)
                        .autocorrectionDisabled()
                }

                Section("Format") {
                    Picker("Format", selection: $formatPreset) {
                        Text("Solo host").tag("solo_host")
                        Text("Two hosts").tag("two_hosts")
                        Text("Rotating guest").tag("rotating_guest")
                    }
                }

                Section("Voice cast") {
                    voiceRow(
                        label: formatPreset == "solo_host" ? "Narrator" : "Host",
                        selectedID: voiceID,
                        excludeID: formatPreset == "two_hosts" ? secondaryVoiceID : nil,
                        onSelect: { voiceID = $0 }
                    )
                    if formatPreset == "two_hosts" {
                        voiceRow(
                            label: "Commenter",
                            selectedID: secondaryVoiceID,
                            excludeID: voiceID,
                            onSelect: { secondaryVoiceID = $0 }
                        )
                    } else if formatPreset == "rotating_guest" {
                        Text("Commenter rotates daily through your other voices.")
                            .font(Theme.Typography.callout)
                            .foregroundStyle(.secondary)
                    }
                    Text("Tap a voice to hear a sample.")
                        .font(Theme.Typography.callout)
                        .foregroundStyle(.secondary)
                }

                Section("Style") {
                    Picker("Tone", selection: $tone) {
                        ForEach(PodcastSetupView.toneOptions, id: \.id) { option in
                            Text(option.label).tag(option.id)
                        }
                    }
                    Picker("Humor", selection: $humorStyle) {
                        ForEach(PodcastSetupView.humorOptions, id: \.id) { option in
                            Text(option.label).tag(option.id)
                        }
                    }
                    Stepper("Key takeaways: \(keyFindingsCount)", value: $keyFindingsCount, in: 3...7)
                    Toggle("Greet me by name", isOn: $personalizedGreeting)
                    Toggle("Include top takeaways", isOn: $includeTopTakeaways)
                    Toggle("Include weather", isOn: $includeWeather)
                    if includeWeather {
                        weatherLocationRow
                    }
                }

                Section("Custom guidance") {
                    Menu {
                        ForEach(PodcastSetupView.guidancePresets) { preset in
                            Button(preset.label) { applyPreset(preset) }
                        }
                    } label: {
                        HStack {
                            Text("Start from a preset…")
                            Spacer()
                            Image(systemName: "chevron.up.chevron.down")
                                .font(.system(size: 12))
                                .foregroundStyle(.secondary)
                        }
                    }
                    TextEditor(text: $customGuidance)
                        .frame(minHeight: 80)
                        .onChange(of: customGuidance) { _, newValue in
                            if newValue.count > PodcastSetupView.guidanceMaxLength {
                                customGuidance = String(newValue.prefix(PodcastSetupView.guidanceMaxLength))
                            }
                        }
                    Text("\(customGuidance.count)/\(PodcastSetupView.guidanceMaxLength)")
                        .font(Theme.Typography.callout)
                        .foregroundStyle(.secondary)
                    Text("Tell the hosts how you'd like the show to feel. Examples: \"Lean technical, skip background.\" \"One dad joke per show, max.\"")
                        .font(Theme.Typography.callout)
                        .foregroundStyle(.secondary)
                }

                Section("Duration") {
                    HStack(spacing: 12) {
                        ForEach(Self.durationOptions, id: \.self) { mins in
                            let isSelected = durationMinutes == mins
                            Button {
                                durationMinutes = mins
                            } label: {
                                Text("\(mins)")
                                    .font(Theme.Typography.subtitle)
                                    .frame(width: 36, height: 36)
                                    .background(isSelected ? Theme.Palette.amber : Color.clear, in: Circle())
                                    .foregroundStyle(isSelected ? Color.white : Theme.Palette.ink)
                                    .overlay(
                                        Circle().stroke(isSelected ? Theme.Palette.amber : Theme.Palette.rule, lineWidth: 1.5)
                                    )
                            }
                            .buttonStyle(.plain)
                        }
                        Spacer()
                        Text("minutes")
                            .font(Theme.Typography.callout)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 4)
                }

                ScheduleSection()

                DeleteAccountSection()
            }
            .navigationTitle("Podcast Setup")
            .navigationBarTitleDisplayMode(.inline)
            .editorialBackground()
            .onAppear {
                displayName = viewModel.user?.displayName ?? ""
                formatPreset = viewModel.profile?.formatPreset ?? "two_hosts"
                durationMinutes = Self.clampDuration(viewModel.profile?.desiredDurationMinutes ?? 3)
                tone = viewModel.profile?.tone ?? "calm_analyst"
                humorStyle = viewModel.profile?.humorStyle ?? "none"
                keyFindingsCount = viewModel.profile?.keyFindingsCount ?? 3
                personalizedGreeting = viewModel.profile?.personalizedGreeting ?? true
                includeTopTakeaways = viewModel.profile?.includeTopTakeaways ?? true
                includeWeather = viewModel.profile?.includeWeather ?? false
                weatherLocation = viewModel.profile?.weatherLocation ?? ""
                customGuidance = viewModel.profile?.customGuidance ?? ""
                customGuidancePresetID = viewModel.profile?.customGuidancePresetID
                applyStoredVoicesIfPossible()
                didLoadInitialState = true
            }
            .onChange(of: viewModel.catalogVoices) { _, _ in
                applyStoredVoicesIfPossible()
            }
            .onChange(of: displayName) { _, newValue in
                guard didLoadInitialState else { return }
                scheduleNameSave(newValue)
            }
            .onChange(of: formatPreset) { _, _ in scheduleConfigSave(immediate: true) }
            .onChange(of: voiceID) { _, _ in scheduleConfigSave(immediate: true) }
            .onChange(of: secondaryVoiceID) { _, _ in scheduleConfigSave(immediate: true) }
            .onChange(of: durationMinutes) { _, _ in scheduleConfigSave(immediate: false) }
            .onChange(of: tone) { _, _ in
                if !isApplyingPreset { customGuidancePresetID = nil }
                scheduleConfigSave(immediate: true)
            }
            .onChange(of: humorStyle) { _, _ in
                if !isApplyingPreset { customGuidancePresetID = nil }
                scheduleConfigSave(immediate: true)
            }
            .onChange(of: keyFindingsCount) { _, _ in
                if !isApplyingPreset { customGuidancePresetID = nil }
                scheduleConfigSave(immediate: true)
            }
            .onChange(of: personalizedGreeting) { _, _ in
                if !isApplyingPreset { customGuidancePresetID = nil }
                scheduleConfigSave(immediate: true)
            }
            .onChange(of: includeTopTakeaways) { _, _ in scheduleConfigSave(immediate: true) }
            .onChange(of: includeWeather) { _, isOn in
                scheduleConfigSave(immediate: true)
                // Auto-detect on first opt-in if we don't already have a cached
                // value to display. User can refresh later via the row's button.
                if isOn, weatherLocation.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    locationResolver.resolve()
                }
            }
            .onChange(of: weatherLocation) { _, _ in scheduleConfigSave(immediate: false) }
            .onChange(of: locationResolver.state) { _, newState in
                if case .resolved(let name) = newState {
                    weatherLocation = name
                }
            }
            .onChange(of: customGuidance) { _, _ in
                if !isApplyingPreset { customGuidancePresetID = nil }
                scheduleConfigSave(immediate: false)
            }
            .onDisappear {
                samplePlayer.stop()
                nameSaveTask?.cancel()
                configSaveTask?.cancel()
            }
        }
    }

    /// Replaces the old "City or ZIP" text field. Drives the user's saved
    /// `weatherLocation` from `LocationResolver.state` and surfaces denial
    /// with a Settings shortcut.
    @ViewBuilder
    private var weatherLocationRow: some View {
        HStack(alignment: .top, spacing: Theme.Spacing.s) {
            Image(systemName: locationIconName)
                .foregroundStyle(Theme.Palette.amberDeep)
                .font(.system(size: 18, weight: .semibold))
                .frame(width: 24)
            VStack(alignment: .leading, spacing: 2) {
                Text("Weather location")
                    .font(Theme.Typography.calloutStrong)
                    .foregroundStyle(.secondary)
                Text(weatherStatusLine)
                    .font(Theme.Typography.body)
                    .foregroundStyle(Theme.Palette.ink)
                if case .denied = locationResolver.state {
                    Button("Open Settings") { openAppSettings() }
                        .font(Theme.Typography.calloutStrong)
                        .padding(.top, 2)
                } else if locationResolver.state != .requesting {
                    Button(weatherLocation.isEmpty ? "Use current location" : "Update") {
                        locationResolver.resolve()
                    }
                    .font(Theme.Typography.calloutStrong)
                    .padding(.top, 2)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 2)
    }

    private var locationIconName: String {
        switch locationResolver.state {
        case .denied: return "location.slash.fill"
        case .requesting: return "location.circle"
        default: return "location.fill"
        }
    }

    private var weatherStatusLine: String {
        switch locationResolver.state {
        case .requesting:
            return "Detecting your location…"
        case .denied:
            return "Location access denied. Enable it in Settings to add weather to your podcast."
        case .error(let message):
            return weatherLocation.isEmpty ? "Couldn't fetch location: \(message)" : weatherLocation
        case .resolved(let name):
            return name
        case .idle:
            return weatherLocation.isEmpty ? "Tap Use current location to detect." : weatherLocation
        }
    }

    private func openAppSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        UIApplication.shared.open(url)
    }

    private func scheduleNameSave(_ value: String) {
        nameSaveTask?.cancel()
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed != viewModel.user?.displayName else { return }
        nameSaveTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 600_000_000)
            guard !Task.isCancelled else { return }
            await viewModel.updateProfile(
                displayName: trimmed,
                timezone: viewModel.user?.timezone ?? TimeZone.current.identifier
            )
        }
    }

    private func scheduleConfigSave(immediate: Bool) {
        guard didLoadInitialState else { return }
        configSaveTask?.cancel()
        configSaveTask = Task { @MainActor in
            if !immediate {
                try? await Task.sleep(nanoseconds: 500_000_000)
                guard !Task.isCancelled else { return }
            }
            let secondary: String? = formatPreset == "two_hosts" ? secondaryVoiceID : nil
            let trimmedLocation = weatherLocation.trimmingCharacters(in: .whitespacesAndNewlines)
            await viewModel.savePodcastConfig(
                title: viewModel.profile?.title ?? "ClawCast",
                formatPreset: formatPreset,
                primaryHost: viewModel.profile?.hostPrimaryName ?? "Host",
                secondaryHost: nil,
                guestNames: [],
                desiredDurationMinutes: durationMinutes,
                voiceID: voiceID,
                secondaryVoiceID: secondary,
                tone: tone,
                keyFindingsCount: keyFindingsCount,
                humorStyle: humorStyle,
                personalizedGreeting: personalizedGreeting,
                includeTopTakeaways: includeTopTakeaways,
                includeWeather: includeWeather,
                weatherLocation: trimmedLocation,
                customGuidance: customGuidance,
                customGuidancePresetID: customGuidancePresetID
            )
        }
    }

    private func applyPreset(_ preset: GuidancePreset) {
        isApplyingPreset = true
        tone = preset.tone
        humorStyle = preset.humorStyle
        keyFindingsCount = preset.keyFindingsCount
        personalizedGreeting = preset.personalizedGreeting
        customGuidance = preset.guidance
        customGuidancePresetID = preset.id
        // Reset the guard on the next runloop tick so onChange handlers (which
        // SwiftUI delivers after the body re-renders) all see the flag set.
        DispatchQueue.main.async { isApplyingPreset = false }
    }

    @ViewBuilder
    private func voiceRow(
        label: String,
        selectedID: String,
        excludeID: String?,
        onSelect: @escaping (String) -> Void
    ) -> some View {
        let selectedVoice = voices.first(where: { $0.id == selectedID })
        let isPlaying = samplePlayer.playingVoiceID == selectedID
        let canPreview = (selectedVoice?.previewURL?.isEmpty == false)
        HStack(spacing: 12) {
            Button {
                guard let voice = selectedVoice, canPreview else { return }
                if isPlaying {
                    samplePlayer.stop()
                } else {
                    samplePlayer.play(voice)
                }
            } label: {
                HStack(spacing: 12) {
                    Image(systemName: isPlaying ? "pause.circle.fill" : "play.circle.fill")
                        .font(.system(size: 20))
                        .foregroundStyle(canPreview ? Theme.Palette.amberDeep : Color.secondary)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(label)
                            .font(Theme.Typography.calloutStrong)
                            .foregroundStyle(.secondary)
                        Text(selectedVoice?.name ?? "Choose a voice")
                            .foregroundStyle(.primary)
                    }
                    Spacer()
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(!canPreview)

            Menu {
                ForEach(voices) { voice in
                    Button {
                        onSelect(voice.id)
                    } label: {
                        if voice.id == excludeID {
                            Label("\(voice.name) (already chosen)", systemImage: "circle.slash")
                        } else if voice.id == selectedID {
                            Label(voice.name, systemImage: "checkmark")
                        } else {
                            Text(voice.name)
                        }
                    }
                    .disabled(voice.id == excludeID)
                }
            } label: {
                HStack(spacing: 4) {
                    Text("Change")
                        .font(Theme.Typography.calloutStrong)
                    Image(systemName: "chevron.down")
                        .font(.system(size: 12, weight: .semibold))
                }
                .foregroundStyle(Theme.Palette.amberDeep)
            }
        }
    }

    private func applyStoredVoicesIfPossible() {
        let available = voices.map(\.id)
        guard !available.isEmpty else { return }
        if let stored = viewModel.profile?.voiceID, available.contains(stored) {
            voiceID = stored
        } else if !available.contains(voiceID) {
            voiceID = available[0]
        }
        if let storedSecondary = viewModel.profile?.secondaryVoiceID,
           available.contains(storedSecondary),
           storedSecondary != voiceID {
            secondaryVoiceID = storedSecondary
        } else if !available.contains(secondaryVoiceID) || secondaryVoiceID == voiceID {
            secondaryVoiceID = available.first(where: { $0 != voiceID }) ?? available.last ?? voiceID
        }
    }
}

struct ScheduleSection: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @State private var selectedDays: Set<String> = ["monday"]
    @State private var deliveryTime: Date = OnboardingScheduleStep.defaultDeliveryTime()
    @State private var didLoadInitialState = false
    @State private var saveTask: Task<Void, Never>?

    private static let dayInitials = ["M", "T", "W", "T", "F", "S", "S"]

    var body: some View {
        Section("Delivery schedule") {
            HStack(spacing: 6) {
                ForEach(Array(OnboardingScheduleStep.canonicalWeekdayOrder.enumerated()), id: \.offset) { idx, day in
                    let isSelected = selectedDays.contains(day)
                    Button {
                        if isSelected {
                            selectedDays.remove(day)
                        } else {
                            selectedDays.insert(day)
                        }
                    } label: {
                        Text(Self.dayInitials[idx])
                            .font(Theme.Typography.subtitle)
                            .frame(width: 32, height: 32)
                            .background(isSelected ? Theme.Palette.amber : Color.clear, in: Circle())
                            .foregroundStyle(isSelected ? Color.white : Theme.Palette.ink)
                            .overlay(
                                Circle().stroke(isSelected ? Theme.Palette.amber : Theme.Palette.rule, lineWidth: 1.5)
                            )
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.vertical, 4)

            DatePicker(
                "Time",
                selection: $deliveryTime,
                displayedComponents: .hourAndMinute
            )
            .tint(Theme.Palette.amberDeep)

            Text("Episodes are delivered in your device's timezone (\(TimeZone.current.identifier)).")
                .font(Theme.Typography.callout)
                .foregroundStyle(.secondary)
        }
        .onAppear {
            selectedDays = Set(viewModel.schedule?.weekdays ?? ["monday"])
            if let parsed = OnboardingScheduleStep.parseHHmm(viewModel.schedule?.localTime) {
                deliveryTime = parsed
            }
            didLoadInitialState = true
        }
        .onChange(of: selectedDays) { _, _ in scheduleSave() }
        .onChange(of: deliveryTime) { _, _ in scheduleSave() }
        .onDisappear { saveTask?.cancel() }
    }

    private func scheduleSave() {
        guard didLoadInitialState else { return }
        guard !selectedDays.isEmpty else { return }
        saveTask?.cancel()
        saveTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 400_000_000)
            guard !Task.isCancelled else { return }
            let weekdays = OnboardingScheduleStep.canonicalWeekdayOrder.filter { selectedDays.contains($0) }
            let timezone = viewModel.user?.timezone ?? TimeZone.current.identifier
            await viewModel.saveSchedule(
                timezone: timezone,
                weekdays: weekdays,
                localTime: OnboardingScheduleStep.formattedHHmm(deliveryTime)
            )
        }
    }
}

/// Final section of PodcastSetupView. Renders a destructive "Delete account"
/// row with a two-step confirmation dialog. On confirm, calls the backend's
/// `DELETE /v1/me` endpoint and clears local state; RootView observes
/// `isAuthenticated` and falls back to SignInView automatically.
struct DeleteAccountSection: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @State private var showConfirm = false

    var body: some View {
        Section("Account") {
            Button(role: .destructive) {
                showConfirm = true
            } label: {
                HStack {
                    Text("Delete account")
                    Spacer()
                    if viewModel.isLoading {
                        ProgressView()
                    }
                }
            }
            .disabled(viewModel.isLoading)

            Text("Permanently removes your profile, sources, schedule, episodes, swipes, and forwarded newsletters. Subscriptions managed through Apple are not cancelled by deleting your account — cancel in Settings → [your name] → Subscriptions if you want to stop billing.")
                .font(Theme.Typography.callout)
                .foregroundStyle(.secondary)
        }
        .confirmationDialog(
            "Delete your ClawCast account?",
            isPresented: $showConfirm,
            titleVisibility: .visible
        ) {
            Button("Delete account", role: .destructive) {
                Task { await viewModel.deleteAccount() }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This cannot be undone. All your data will be removed.")
        }
    }
}

// MARK: - Feed access

struct FeedAccessView: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @State private var copied = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.Spacing.l) {
                    EditorialCard {
                        MetaLabel(text: "Step 1")
                        Text("Add to Apple Podcasts")
                            .font(Theme.Typography.title)
                            .foregroundStyle(Theme.Palette.ink)
                        Text("Tap below to open Apple Podcasts with your private feed pre-loaded.")
                            .font(Theme.Typography.body)
                            .foregroundStyle(Theme.Palette.inkSoft)

                        Button {
                            openInApplePodcasts()
                        } label: {
                            Label("Open in Apple Podcasts", systemImage: "play.fill")
                        }
                        .buttonStyle(.amberFilled)
                        .disabled(viewModel.feed?.feedURL == nil)
                    }

                    EditorialCard {
                        MetaLabel(text: "Step 2 · Manual")
                        Text("Or add by URL")
                            .font(Theme.Typography.title)
                            .foregroundStyle(Theme.Palette.ink)

                        Text(viewModel.feed?.feedURL ?? "Sign in to generate your private feed.")
                            .font(.system(size: 13, design: .monospaced))
                            .foregroundStyle(Theme.Palette.inkSoft)
                            .padding(Theme.Spacing.s)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Theme.Palette.creamDeep, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                            .textSelection(.enabled)

                        Button {
                            UIPasteboard.general.string = viewModel.feed?.feedURL
                            copied = true
                            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { copied = false }
                        } label: {
                            Label(copied ? "Copied" : "Copy feed link", systemImage: copied ? "checkmark" : "doc.on.doc")
                        }
                        .buttonStyle(.amberOutlined)
                        .disabled(viewModel.feed?.feedURL == nil)

                        Text("In Apple Podcasts: Library → … menu → Follow a Show by URL → paste.")
                            .font(Theme.Typography.callout)
                            .foregroundStyle(Theme.Palette.muted)
                    }

                    if let latestRun = viewModel.feed?.latestRun {
                        EditorialCard {
                            MetaLabel(text: "Latest run")
                            HStack {
                                Text(latestRun.status.capitalized)
                                    .font(Theme.Typography.subtitle)
                                    .foregroundStyle(Theme.Palette.ink)
                                Spacer()
                                if latestRun.capHit {
                                    Text("Cap hit")
                                        .font(Theme.Typography.meta)
                                        .foregroundStyle(Theme.Palette.amberDeep)
                                        .padding(.horizontal, 8)
                                        .padding(.vertical, 4)
                                        .background(Theme.Palette.amber.opacity(0.15), in: Capsule())
                                }
                            }
                            Text(latestRun.message)
                                .font(Theme.Typography.callout)
                                .foregroundStyle(Theme.Palette.inkSoft)
                        }
                    }
                }
                .padding(.horizontal, Theme.Spacing.l)
                .padding(.top, Theme.Spacing.s)
                .padding(.bottom, Theme.Spacing.xl)
            }
            .navigationTitle("Feed Access")
            .editorialBackground()
        }
    }

    private func openInApplePodcasts() {
        guard let urlString = viewModel.feed?.feedURL,
              let url = URL(string: urlString),
              let host = url.host else { return }
        var components = URLComponents()
        components.scheme = "podcast"
        components.host = host
        components.path = url.path
        if let podcastURL = components.url {
            UIApplication.shared.open(podcastURL) { ok in
                if !ok { UIApplication.shared.open(url) }
            }
        }
    }
}

// MARK: - Paywall

struct PaywallView: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.Spacing.l) {
                    headerCard
                    trialStatusCard
                    comparisonCard
                    plansSection
                    if let message = viewModel.purchaseManager.lastPurchaseMessage {
                        statusCard(message: message)
                    }
                    legalFooter
                }
                .padding(.horizontal, Theme.Spacing.l)
                .padding(.top, Theme.Spacing.s)
                .padding(.bottom, Theme.Spacing.xl)
            }
            .navigationTitle("Upgrade")
            .editorialBackground()
        }
    }

    private var currentTierLabel: String {
        if viewModel.isMax { return "You're on Max" }
        if viewModel.isPro { return "You're on Pro" }
        return "Go further"
    }

    private var headerHeadline: String {
        if viewModel.isPaid { return "You're all set" }
        return "Unlock daily briefings"
    }

    private var headerBody: String {
        if viewModel.isPaid {
            return "Your subscription is active. Manage or cancel in Settings → Apple ID → Subscriptions."
        }
        return "Pro: 3 premium-voice pods/week + 4 default-voice pods/week. Max: 7 premium-voice pods/week. Cancel anytime."
    }

    private var headerCard: some View {
        EditorialCard {
            MetaLabel(text: currentTierLabel)
            Text(headerHeadline)
                .font(Theme.Typography.title)
                .foregroundStyle(Theme.Palette.ink)
            Text(headerBody)
                .font(Theme.Typography.body)
                .foregroundStyle(Theme.Palette.inkSoft)
        }
    }

    @ViewBuilder
    private var trialStatusCard: some View {
        if let entitlements = viewModel.entitlements, !viewModel.isPaid {
            if entitlements.isInTrial && entitlements.trialPremiumPodsRemaining > 0 {
                EditorialCard {
                    MetaLabel(text: "Free trial")
                    Text("\(entitlements.trialPremiumPodsRemaining) premium-voice pods left in your trial")
                        .font(Theme.Typography.calloutStrong)
                        .foregroundStyle(Theme.Palette.ink)
                    Text("After your trial, free users get 1 premium-voice pod/week for the first month, then 1 default-voice pod/week.")
                        .font(Theme.Typography.callout)
                        .foregroundStyle(Theme.Palette.inkSoft)
                }
            } else if entitlements.isInFirstMonth {
                EditorialCard {
                    MetaLabel(text: "Free · First month")
                    Text("\(entitlements.premiumPodsRemainingThisWeek) premium-voice pod left this week")
                        .font(Theme.Typography.calloutStrong)
                        .foregroundStyle(Theme.Palette.ink)
                    Text("After your first month ends, free users get 1 default-voice pod/week. Upgrade to keep premium voices flowing daily.")
                        .font(Theme.Typography.callout)
                        .foregroundStyle(Theme.Palette.inkSoft)
                }
            } else {
                EditorialCard {
                    MetaLabel(text: "Free")
                    Text("1 default-voice pod/week")
                        .font(Theme.Typography.calloutStrong)
                        .foregroundStyle(Theme.Palette.ink)
                    Text("Upgrade for premium voices and daily delivery.")
                        .font(Theme.Typography.callout)
                        .foregroundStyle(Theme.Palette.inkSoft)
                }
            }
        }
    }

    private var comparisonCard: some View {
        EditorialCard {
            MetaLabel(text: "What you get")
            VStack(spacing: Theme.Spacing.s) {
                comparisonRow(label: "Premium-voice pods / wk", free: "0¹", pro: "3", max: "7")
                EditorialDivider()
                comparisonRow(label: "Default-voice pods / wk", free: "1", pro: "4", max: "0")
                EditorialDivider()
                comparisonRow(label: "Episode length", free: "3–5 min", pro: "3–5 min", max: "3–5 min")
            }
            Text("¹ Free trial: 5 premium pods. First month: 1 premium pod/week.")
                .font(Theme.Typography.meta)
                .foregroundStyle(Theme.Palette.muted)
                .padding(.top, Theme.Spacing.xs)
        }
    }

    private func comparisonRow(label: String, free: String, pro: String, max: String) -> some View {
        HStack(spacing: Theme.Spacing.xs) {
            Text(label)
                .font(Theme.Typography.body)
                .foregroundStyle(Theme.Palette.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
            VStack(spacing: 2) {
                Text("Free").font(Theme.Typography.meta).foregroundStyle(Theme.Palette.muted)
                Text(free).font(Theme.Typography.callout).foregroundStyle(Theme.Palette.inkSoft)
            }
            .frame(width: 60)
            VStack(spacing: 2) {
                Text("Pro").font(Theme.Typography.meta).foregroundStyle(Theme.Palette.amberDeep)
                Text(pro).font(Theme.Typography.calloutStrong).foregroundStyle(Theme.Palette.ink)
            }
            .frame(width: 60)
            VStack(spacing: 2) {
                Text("Max").font(Theme.Typography.meta).foregroundStyle(Theme.Palette.amberDeep)
                Text(max).font(Theme.Typography.calloutStrong).foregroundStyle(Theme.Palette.ink)
            }
            .frame(width: 60)
        }
    }

    @ViewBuilder
    private var plansSection: some View {
        if viewModel.purchaseManager.isLoading {
            EditorialCard {
                ProgressView("Loading plans…")
                    .frame(maxWidth: .infinity)
            }
        } else if viewModel.purchaseManager.products.isEmpty {
            EditorialCard {
                MetaLabel(text: "Plans unavailable")
                Text("We couldn't load subscription plans from the App Store.")
                    .font(Theme.Typography.body)
                    .foregroundStyle(Theme.Palette.ink)
                Text("Make sure these product IDs are configured in App Store Connect:")
                    .font(Theme.Typography.callout)
                    .foregroundStyle(Theme.Palette.muted)
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(AppConfiguration.allProductIDs, id: \.self) { productID in
                        Text("• \(productID)")
                    }
                }
                .font(.system(size: 12, design: .monospaced))
                .foregroundStyle(Theme.Palette.inkSoft)

                Button("Retry") {
                    Task { await viewModel.purchaseManager.loadProducts() }
                }
                .buttonStyle(.amberOutlined)
            }
        } else {
            ForEach(viewModel.purchaseManager.products, id: \.id) { product in
                PlanCard(product: product)
            }
        }
    }

    private func statusCard(message: String) -> some View {
        EditorialCard {
            MetaLabel(text: "Purchase status")
            Text(message)
                .font(Theme.Typography.callout)
                .foregroundStyle(Theme.Palette.inkSoft)
        }
    }

    private var legalFooter: some View {
        VStack(spacing: 6) {
            Text("Subscriptions auto-renew until cancelled. Manage or cancel in Settings → Apple ID → Subscriptions.")
                .font(Theme.Typography.callout)
                .foregroundStyle(Theme.Palette.muted)
                .multilineTextAlignment(.center)
            HStack(spacing: 16) {
                Link("Terms of Use", destination: AppConfiguration.termsURL)
                Text("·").foregroundStyle(Theme.Palette.muted)
                Link("Privacy Policy", destination: AppConfiguration.privacyURL)
                Text("·").foregroundStyle(Theme.Palette.muted)
                Button("Restore") {
                    Task {
                        try? await AppStore.sync()
                        try? await viewModel.refresh()
                    }
                }
            }
            .font(Theme.Typography.callout)
            .tint(Theme.Palette.amberDeep)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, Theme.Spacing.s)
    }
}

private struct PlanCard: View {
    @EnvironmentObject private var viewModel: AppViewModel
    let product: Product

    var body: some View {
        EditorialCard {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(product.displayName)
                        .font(Theme.Typography.title)
                        .foregroundStyle(Theme.Palette.ink)
                    if !product.description.isEmpty {
                        Text(product.description)
                            .font(Theme.Typography.callout)
                            .foregroundStyle(Theme.Palette.muted)
                    }
                }
                Spacer()
                Text(product.displayPrice)
                    .font(Theme.Typography.subtitle)
                    .foregroundStyle(Theme.Palette.amberDeep)
            }

            Button {
                guard let userID = viewModel.user?.id else { return }
                Task {
                    await viewModel.purchaseManager.purchase(product: product, userID: userID)
                    try? await viewModel.refresh()
                }
            } label: {
                Text("Subscribe")
            }
            .buttonStyle(.amberFilled)
        }
    }
}

// MARK: - Onboarding

struct OnboardingStarterPack: Identifiable {
    let id: String
    let name: String
    let icon: String
    let sourceIDs: [String]
    let sourceNames: [String]

    /// Truncated preview shown when the card is collapsed.
    var summary: String {
        let preview = sourceNames.prefix(3).joined(separator: ", ")
        return sourceNames.count > 3 ? "\(preview), + \(sourceNames.count - 3) more" : preview
    }

    /// Full comma-separated list shown when the card is expanded.
    var fullList: String {
        sourceNames.joined(separator: ", ")
    }

    var hasMore: Bool {
        sourceNames.count > 3
    }

    // SF Symbols per topic. Unknown topics fall back to "sparkles".
    private static let iconByTopic: [String: String] = [
        "News": "newspaper.fill",
        "Politics": "building.columns.fill",
        "Business": "chart.line.uptrend.xyaxis",
        "Tech": "cpu.fill",
        "Strategy": "target",
        "Personal Finance": "dollarsign.circle.fill",
        "Science": "atom",
        "Sports": "sportscourt.fill",
        "Culture": "theatermasks.fill",
        "Health & Wellness": "heart.fill",
        "Food & Travel": "airplane",
        "Romantasy": "heart.text.square.fill",
    ]

    /// Curated balanced mix used by the "Inspire me" shortcut. Listed in priority
    /// order; only topics actually present in the live catalog are used.
    static let inspireMeTopics: [String] = ["News", "Tech", "Culture", "Personal Finance"]

    static func icon(forTopic topic: String) -> String {
        iconByTopic[topic] ?? "sparkles"
    }

    /// Build topic-grouped starter packs from the live source catalog.
    /// Topics appear in the order their first source is encountered, matching `sources.yml` order.
    static func packs(from catalog: [CatalogSourceDTO]) -> [OnboardingStarterPack] {
        var topicOrder: [String] = []
        var bucket: [String: [CatalogSourceDTO]] = [:]
        for source in catalog where source.enabled {
            guard let topic = source.topic, !topic.isEmpty else { continue }
            if bucket[topic] == nil {
                topicOrder.append(topic)
                bucket[topic] = []
            }
            bucket[topic]?.append(source)
        }
        return topicOrder.map { topic in
            let sources = bucket[topic] ?? []
            return OnboardingStarterPack(
                id: topic,
                name: topic,
                icon: iconByTopic[topic] ?? "sparkles",
                sourceIDs: sources.map(\.sourceID),
                sourceNames: sources.map(\.name)
            )
        }
    }
}

struct OnboardingShowPreset: Identifiable {
    let id: String
    let name: String
    let tagline: String
    let description: String
    let formatPreset: String
    let primaryHost: String
    let secondaryHost: String?
    let durationMinutes: Int
    let recommended: Bool
    let requiresPaid: Bool

    /// Whether the user must pick a commentator voice in the Voices step.
    /// `rotating_guest` ignores the user's secondary voice on the backend
    /// (it cycles through the catalog daily), so we don't ask for one.
    var requiresCommentatorPick: Bool {
        formatPreset == "two_hosts"
    }

    static let all: [OnboardingShowPreset] = [
        OnboardingShowPreset(
            id: "solo",
            name: "Solo host",
            tagline: "5 minutes • one host",
            description: "Just one voice walking through the day's items.",
            formatPreset: "solo_host",
            primaryHost: "Vinnie",
            secondaryHost: nil,
            durationMinutes: 5,
            recommended: false,
            requiresPaid: false
        ),
        OnboardingShowPreset(
            id: "twohost",
            name: "Two-host show",
            tagline: "5 minutes • two hosts",
            description: "Two voices trade off — one anchors, the other reacts and chimes in.",
            formatPreset: "two_hosts",
            primaryHost: "Vinnie",
            secondaryHost: "Demi",
            durationMinutes: 5,
            recommended: true,
            requiresPaid: false
        ),
        OnboardingShowPreset(
            id: "rotating",
            name: "Rotating guest",
            tagline: "5 minutes • host + rotating guest",
            description: "An anchor plus a different guest voice each episode, drawn from the full voice catalog.",
            formatPreset: "rotating_guest",
            primaryHost: "Vinnie",
            secondaryHost: nil,
            durationMinutes: 5,
            recommended: false,
            requiresPaid: false
        ),
    ]
}

enum OnboardingScheduleChoice: String, CaseIterable, Identifiable {
    case daily, weekdays, weekly

    var id: String { rawValue }

    var label: String {
        switch self {
        case .daily: return "Daily"
        case .weekdays: return "Weekdays"
        case .weekly: return "Weekly"
        }
    }

    var detail: String {
        switch self {
        case .daily: return "Every day at 7:00 AM local time."
        case .weekdays: return "Monday through Friday at 7:00 AM."
        case .weekly: return "Mondays at 7:00 AM."
        }
    }

    var weekdays: [String] {
        switch self {
        case .daily:
            return ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        case .weekdays:
            return ["monday", "tuesday", "wednesday", "thursday", "friday"]
        case .weekly:
            return ["monday"]
        }
    }

    var requiresPaid: Bool {
        // Only Daily exceeds the free 5-day cap.
        self == .daily
    }
}

struct OnboardingFlowView: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @State private var step: Int = 0
    @State private var selectedShowPresetID: String = "twohost"
    @State private var selectedAnchorVoiceID: String? = nil
    @State private var selectedCommentatorVoiceID: String? = nil
    @State private var selectedWeekdays: Set<String> = Set(OnboardingScheduleChoice.weekdays.weekdays)
    @State private var selectedDeliveryTime: Date = OnboardingScheduleStep.defaultDeliveryTime()

    /// True when the user picked the solo-host preset; the Voices step is skipped
    /// since there's no commentator role to assign.
    private var isSoloHostPreset: Bool {
        OnboardingShowPreset.all.first(where: { $0.id == selectedShowPresetID })?.formatPreset == "solo_host"
    }

    private var requiresCommentator: Bool {
        OnboardingShowPreset.all.first(where: { $0.id == selectedShowPresetID })?.requiresCommentatorPick ?? false
    }

    private var totalSteps: Int {
        // Welcome, Voice intake, Swipe deck, Newsletters, Show, [Voices], Schedule, Alias card
        isSoloHostPreset ? 7 : 8
    }

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                Theme.Palette.cream.ignoresSafeArea()
                stepContent
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    OnboardingProgressDots(current: step, total: totalSteps)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    if step < totalSteps - 1 {
                        Button("Skip") { viewModel.completeOnboarding() }
                            .foregroundStyle(Theme.Palette.muted)
                    }
                }
            }
            .toolbarBackground(Theme.Palette.cream, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
        }
        .tint(Theme.Palette.amberDeep)
    }

    @ViewBuilder
    private var stepContent: some View {
        switch step {
        case 0:
            OnboardingWelcomeStep(
                firstName: firstName,
                onContinue: { step = 1 }
            )
        case 1:
            OnboardingVoiceIntakeStep(
                onBack: { step = 0 },
                onContinue: { step = 2 }
            )
        case 2:
            OnboardingSwipeStep(
                onBack: { step = 1 },
                onContinue: { step = 3 }
            )
        case 3:
            OnboardingNewslettersStep(
                onBack: { step = 2 },
                onContinue: { step = 4 }
            )
        case 4:
            OnboardingShowStep(
                selected: $selectedShowPresetID,
                isPaid: viewModel.isPaid,
                onBack: { step = 3 },
                onContinue: {
                    Task {
                        await saveShowPreset()
                        // Solo-host has no commentator role, so skip the Voices step.
                        step = isSoloHostPreset ? 6 : 5
                    }
                }
            )
        case 5:
            OnboardingVoicesStep(
                anchorVoiceID: $selectedAnchorVoiceID,
                commentatorVoiceID: $selectedCommentatorVoiceID,
                requiresCommentator: requiresCommentator,
                onBack: { step = 4 },
                onContinue: {
                    Task {
                        await saveVoicesSelection()
                        step = 6
                    }
                }
            )
        case 6:
            OnboardingScheduleStep(
                selectedWeekdays: $selectedWeekdays,
                deliveryTime: $selectedDeliveryTime,
                maxDeliveryDays: viewModel.entitlements?.maxDeliveryDays ?? 5,
                onBack: { step = isSoloHostPreset ? 4 : 5 },
                onContinue: {
                    Task {
                        await saveSchedule()
                        step = 7
                    }
                }
            )
        default:
            OnboardingAliasStep(
                onFinish: { viewModel.completeOnboarding() }
            )
        }
    }

    private var firstName: String {
        viewModel.user?.firstName ?? ""
    }

    private func saveShowPreset() async {
        guard let preset = OnboardingShowPreset.all.first(where: { $0.id == selectedShowPresetID }) else { return }
        let title = (viewModel.profile?.title.isEmpty == false) ? viewModel.profile!.title : "ClawCast"
        // Voice is set by the Voices step on the next screen — keep whatever's already on
        // the profile (default Vinnie) so we don't blow away an in-progress voice choice.
        let voiceID = viewModel.profile?.voiceID ?? PodcastSetupView.voiceOptions[0].id
        await viewModel.savePodcastConfig(
            title: title,
            formatPreset: preset.formatPreset,
            primaryHost: preset.primaryHost,
            secondaryHost: preset.secondaryHost,
            guestNames: [],
            desiredDurationMinutes: preset.durationMinutes,
            voiceID: voiceID
        )
    }

    private func saveVoicesSelection() async {
        guard let anchorID = selectedAnchorVoiceID,
              let preset = OnboardingShowPreset.all.first(where: { $0.id == selectedShowPresetID }) else { return }
        let title = viewModel.profile?.title.isEmpty == false ? viewModel.profile!.title : "ClawCast"
        let secondaryID: String? = preset.formatPreset == "two_hosts" ? selectedCommentatorVoiceID : nil
        await viewModel.savePodcastConfig(
            title: title,
            formatPreset: preset.formatPreset,
            primaryHost: preset.primaryHost,
            secondaryHost: preset.secondaryHost,
            guestNames: [],
            desiredDurationMinutes: preset.durationMinutes,
            voiceID: anchorID,
            secondaryVoiceID: secondaryID
        )
    }

    private func saveSchedule() async {
        let timezone = viewModel.user?.timezone ?? TimeZone.current.identifier
        let weekdays = OnboardingScheduleStep.canonicalWeekdayOrder.filter { selectedWeekdays.contains($0) }
        let localTime = OnboardingScheduleStep.formattedHHmm(selectedDeliveryTime)
        await viewModel.saveSchedule(timezone: timezone, weekdays: weekdays, localTime: localTime)
    }
}

private struct OnboardingProgressDots: View {
    let current: Int
    let total: Int

    var body: some View {
        HStack(spacing: 6) {
            ForEach(0..<total, id: \.self) { index in
                Circle()
                    .fill(index <= current ? Theme.Palette.amber : Theme.Palette.rule)
                    .frame(width: 6, height: 6)
            }
        }
    }
}

private struct OnboardingStepShell<Content: View>: View {
    let title: String
    let subtitle: String
    let primaryLabel: String
    let primaryDisabled: Bool
    let onPrimary: () -> Void
    let onBack: (() -> Void)?
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.m) {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.Spacing.l) {
                    VStack(alignment: .leading, spacing: Theme.Spacing.s) {
                        Text(title)
                            .font(Theme.Typography.display)
                            .foregroundStyle(Theme.Palette.ink)
                            .fixedSize(horizontal: false, vertical: true)
                        Text(subtitle)
                            .font(Theme.Typography.body)
                            .foregroundStyle(Theme.Palette.inkSoft)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    content()
                }
                .padding(.horizontal, Theme.Spacing.l)
                .padding(.top, Theme.Spacing.m)
                .padding(.bottom, Theme.Spacing.l)
            }

            VStack(spacing: Theme.Spacing.s) {
                Button(action: onPrimary) {
                    Text(primaryLabel)
                }
                .buttonStyle(.amberFilled)
                .disabled(primaryDisabled)

                if let onBack {
                    Button(action: onBack) {
                        Text("Back")
                    }
                    .buttonStyle(.amberOutlined)
                }
            }
            .padding(.horizontal, Theme.Spacing.l)
            .padding(.bottom, Theme.Spacing.l)
        }
    }
}

private struct OnboardingWelcomeStep: View {
    let firstName: String
    let onContinue: () -> Void

    var body: some View {
        OnboardingStepShell(
            title: greeting,
            subtitle: "Your own podcast, hosted by AI voices, made from the news and writers you actually want to follow. Let's set it up.",
            primaryLabel: "Set up my podcast",
            primaryDisabled: false,
            onPrimary: onContinue,
            onBack: nil
        ) {
            VStack(alignment: .leading, spacing: Theme.Spacing.l) {
                bullet(
                    number: "1",
                    title: "Choose your sources",
                    text: "Pick topics or paste in your own feeds. We'll pull the latest stories. After set-up, you'll get your own email address you can use to subscribe to newsletters and have them added to your podcast."
                )
                bullet(
                    number: "2",
                    title: "Pick the hosts",
                    text: "Choose one or two AI voices to read and riff on the day's items."
                )
                bullet(
                    number: "3",
                    title: "Listen in Apple Podcasts",
                    text: "New episodes show up in Apple Podcasts on the days you choose."
                )
            }
            .padding(.horizontal, Theme.Spacing.s)
        }
    }

    private var greeting: String {
        firstName.isEmpty ? "Welcome to ClawCast." : "Hi \(firstName) — welcome to ClawCast."
    }

    /// Numbered info row, intentionally NOT wrapped in EditorialCard so it doesn't read as tappable.
    private func bullet(number: String, title: String, text: String) -> some View {
        HStack(alignment: .top, spacing: Theme.Spacing.m) {
            Text(number)
                .font(Theme.Typography.title)
                .foregroundStyle(Theme.Palette.amberDeep)
                .frame(width: 28, alignment: .leading)
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(Theme.Typography.subtitle)
                    .foregroundStyle(Theme.Palette.ink)
                Text(text)
                    .font(Theme.Typography.callout)
                    .foregroundStyle(Theme.Palette.inkSoft)
            }
        }
    }
}

// MARK: - New onboarding steps (voice intake, swipe deck, newsletters, alias)

private struct OnboardingVoiceIntakeStep: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @StateObject private var dictation = FeedbackDictation()
    @State private var isSubmitting: Bool = false
    @State private var lastAck: VoiceIntakeAck?
    let onBack: () -> Void
    let onContinue: () -> Void

    var body: some View {
        OnboardingStepShell(
            title: "Tell me what's on your mind.",
            subtitle: "Tap the mic and talk for up to a minute — what you've been reading, who you follow, what you'd like to hear more about. Skip this if you'd rather let swipes do the work.",
            primaryLabel: primaryLabel,
            primaryDisabled: primaryDisabled,
            onPrimary: primaryAction,
            onBack: onBack
        ) {
            VStack(alignment: .leading, spacing: Theme.Spacing.l) {
                examplePrompts
                micCard
                if let error = dictation.errorMessage {
                    Text(error)
                        .font(Theme.Typography.callout)
                        .foregroundStyle(.red)
                }
                if let ack = lastAck {
                    extractedSummary(ack: ack)
                }
                Button(action: onContinue) {
                    Text("Skip — let the system learn from swipes")
                        .font(Theme.Typography.callout)
                        .foregroundStyle(Theme.Palette.muted)
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var trimmedTranscript: String {
        dictation.transcript.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var primaryLabel: String {
        if isSubmitting { return "Saving…" }
        if lastAck != nil { return "Continue" }
        return "Save"
    }

    private var primaryDisabled: Bool {
        if isSubmitting { return true }
        if lastAck != nil { return false }
        return trimmedTranscript.isEmpty
    }

    private func primaryAction() {
        if lastAck != nil {
            onContinue()
        } else {
            submit()
        }
    }

    private var examplePrompts: some View {
        VStack(alignment: .leading, spacing: 6) {
            MetaLabel(text: "Try saying")
            ForEach(
                [
                    "I've been chasing the AI compute story.",
                    "I read Stratechery and Platformer every week.",
                    "I'm into Premier League, my partner is into longevity.",
                ],
                id: \.self
            ) { example in
                Text("“\(example)”")
                    .font(Theme.Typography.callout)
                    .foregroundStyle(Theme.Palette.inkSoft)
            }
        }
    }

    private var micCard: some View {
        EditorialCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.m) {
                HStack(spacing: Theme.Spacing.m) {
                    Button(action: toggle) {
                        ZStack {
                            Circle()
                                .fill(dictation.isRecording ? Color.red : Theme.Palette.amberDeep)
                                .frame(width: 64, height: 64)
                            Image(systemName: dictation.isRecording ? "stop.fill" : "mic.fill")
                                .font(.system(size: 26, weight: .semibold))
                                .foregroundStyle(.white)
                        }
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(dictation.isRecording ? "Stop recording" : "Start recording")
                    VStack(alignment: .leading, spacing: 2) {
                        Text(dictation.isRecording ? "Listening…" : trimmedTranscript.isEmpty ? "Tap to start" : "Tap to record again")
                            .font(Theme.Typography.subtitle)
                            .foregroundStyle(Theme.Palette.ink)
                        Text("On-device transcription. We never send raw audio.")
                            .font(Theme.Typography.meta)
                            .foregroundStyle(Theme.Palette.muted)
                    }
                    Spacer(minLength: 0)
                }
                if !trimmedTranscript.isEmpty {
                    Text(dictation.transcript)
                        .font(Theme.Typography.body)
                        .foregroundStyle(Theme.Palette.ink)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private func extractedSummary(ack: VoiceIntakeAck) -> some View {
        EditorialCard {
            VStack(alignment: .leading, spacing: 6) {
                MetaLabel(text: "Got it")
                if !ack.topics.isEmpty {
                    Text("Topics: " + ack.topics.joined(separator: ", "))
                        .font(Theme.Typography.callout)
                        .foregroundStyle(Theme.Palette.ink)
                }
                if !ack.namedEntities.isEmpty {
                    Text("Names: " + ack.namedEntities.joined(separator: ", "))
                        .font(Theme.Typography.callout)
                        .foregroundStyle(Theme.Palette.ink)
                }
                if let vibe = ack.vibeNotes, !vibe.isEmpty {
                    Text("Style: " + vibe)
                        .font(Theme.Typography.callout)
                        .foregroundStyle(Theme.Palette.ink)
                }
                if ack.topics.isEmpty && ack.namedEntities.isEmpty && (ack.vibeNotes ?? "").isEmpty {
                    Text("We'll mostly lean on your swipes from here.")
                        .font(Theme.Typography.callout)
                        .foregroundStyle(Theme.Palette.muted)
                }
            }
        }
    }

    private func toggle() {
        if dictation.isRecording {
            dictation.stop()
        } else {
            lastAck = nil
            Task { await dictation.start() }
        }
    }

    private func submit() {
        let transcript = trimmedTranscript
        guard !transcript.isEmpty, !isSubmitting else { return }
        isSubmitting = true
        Task {
            let result = await viewModel.submitVoiceIntake(transcript: transcript)
            await MainActor.run {
                isSubmitting = false
                lastAck = result
            }
        }
    }
}

private struct OnboardingSwipeStep: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @State private var cards: [SwipeDeckCardDTO] = []
    @State private var swipeCount: Int = 0
    @State private var isLoading: Bool = true
    @State private var didApplyDefaults: Bool = false
    let onBack: () -> Void
    let onContinue: () -> Void

    private let targetSwipeCount = 8

    var body: some View {
        OnboardingStepShell(
            title: "What grabs you?",
            subtitle: "Right for more like this, left to skip. \(targetSwipeCount) cards is enough to start — we're seeding a balanced default mix in the background so you have coverage either way.",
            primaryLabel: primaryLabel,
            primaryDisabled: primaryDisabled,
            onPrimary: onContinue,
            onBack: onBack
        ) {
            VStack(spacing: Theme.Spacing.m) {
                if isLoading {
                    ProgressView()
                        .controlSize(.large)
                        .padding(.top, Theme.Spacing.xl)
                } else if cards.isEmpty {
                    VStack(spacing: Theme.Spacing.s) {
                        Text("No cards available yet.")
                            .font(Theme.Typography.body)
                            .foregroundStyle(Theme.Palette.inkSoft)
                        Text("That's fine — we'll learn from your first episode and the Tune Your Pod deck.")
                            .font(Theme.Typography.callout)
                            .foregroundStyle(Theme.Palette.muted)
                    }
                    .padding(.vertical, Theme.Spacing.xl)
                } else {
                    SwipeDeckCardStack(cards: $cards) { card, direction in
                        swipeCount += 1
                        Task { await viewModel.submitSwipe(card: card, direction: direction) }
                    }
                    .frame(maxWidth: .infinity, minHeight: 380)
                    Text(progressLabel)
                        .font(Theme.Typography.meta)
                        .foregroundStyle(Theme.Palette.muted)
                }
                Button(action: onContinue) {
                    Text("Skip — let the first episode pick for me")
                        .font(Theme.Typography.callout)
                        .foregroundStyle(Theme.Palette.muted)
                }
                .buttonStyle(.plain)
            }
        }
        .task { await loadDeck() }
    }

    private var primaryLabel: String {
        if swipeCount >= targetSwipeCount || cards.isEmpty { return "Continue" }
        return "Continue (\(targetSwipeCount - swipeCount) more)"
    }

    private var primaryDisabled: Bool {
        cards.isEmpty ? false : swipeCount < targetSwipeCount
    }

    private var progressLabel: String {
        "\(min(swipeCount, targetSwipeCount)) / \(targetSwipeCount) swiped"
    }

    private func loadDeck() async {
        if !didApplyDefaults {
            await applyCuratedDefaults()
            didApplyDefaults = true
        }
        cards = await viewModel.fetchColdStartSwipeDeck()
        isLoading = false
    }

    private func applyCuratedDefaults() async {
        // No catalog sources attached yet? Apply the curated "Inspire me" mix so
        // the user has something to ingest from on day one even if they skip
        // every swipe.
        guard viewModel.selectedSources.isEmpty else { return }
        let packs = OnboardingStarterPack.packs(from: viewModel.catalogSources)
        let availableIDs = Set(packs.map(\.id))
        let curated = OnboardingStarterPack.inspireMeTopics.filter { availableIDs.contains($0) }
        let sourceIDs = Set(
            packs.filter { curated.contains($0.id) }.flatMap { $0.sourceIDs }
        )
        guard !sourceIDs.isEmpty else { return }
        await viewModel.saveSources(catalogIDs: Array(sourceIDs), customURLs: [])
    }
}

private struct OnboardingNewslettersStep: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @StateObject private var dictation = FeedbackDictation()
    @State private var input: String = ""
    @State private var candidates: [SubstackCandidateDTO] = []
    @State private var registered: [SubstackIntentDTO] = []
    @State private var addingCandidateID: String?
    @State private var isSearching: Bool = false
    @State private var lastError: String?
    @State private var hasSearched: Bool = false
    let onBack: () -> Void
    let onContinue: () -> Void

    private let maxEntries = 5

    var body: some View {
        OnboardingStepShell(
            title: "What newsletters do you read?",
            subtitle: "Describe what you're into in a sentence — we'll find Substacks that match and you can confirm the right ones. Or paste a handle directly if you already know one.",
            primaryLabel: "Continue",
            primaryDisabled: false,
            onPrimary: onContinue,
            onBack: onBack
        ) {
            VStack(alignment: .leading, spacing: Theme.Spacing.m) {
                queryRow
                if let error = dictation.errorMessage {
                    Text(error)
                        .font(Theme.Typography.callout)
                        .foregroundStyle(.red)
                }
                if let lastError {
                    Text(lastError)
                        .font(Theme.Typography.callout)
                        .foregroundStyle(.red)
                }
                if isSearching {
                    HStack(spacing: Theme.Spacing.s) {
                        ProgressView()
                        Text("Searching…")
                            .font(Theme.Typography.callout)
                            .foregroundStyle(Theme.Palette.muted)
                    }
                }
                if !candidates.isEmpty {
                    suggestionsList
                } else if hasSearched && !isSearching {
                    Text("No clear matches — try describing it differently, or paste a handle below.")
                        .font(Theme.Typography.callout)
                        .foregroundStyle(Theme.Palette.muted)
                } else if !hasSearched && !isSearching {
                    Text("Try: \"AI strategy and platform regulation\", or \"longevity research and habits\", or just \"@stratechery\".")
                        .font(Theme.Typography.callout)
                        .foregroundStyle(Theme.Palette.muted)
                }
                if !registered.isEmpty {
                    Divider().padding(.vertical, 4)
                    MetaLabel(text: "Added to your pod")
                    ForEach(registered) { intent in
                        registeredRow(intent)
                    }
                }
                Button(action: onContinue) {
                    Text("Skip — I don't have any in mind")
                        .font(Theme.Typography.callout)
                        .foregroundStyle(Theme.Palette.muted)
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var queryRow: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.s) {
            HStack(spacing: Theme.Spacing.s) {
                TextField("Describe what you read…", text: $input, axis: .vertical)
                    .lineLimit(1...3)
                    .textInputAutocapitalization(.sentences)
                    .padding(Theme.Spacing.s)
                    .background(Color.white, in: RoundedRectangle(cornerRadius: 10))
                    .overlay(
                        RoundedRectangle(cornerRadius: 10)
                            .stroke(Theme.Palette.rule, lineWidth: 1)
                    )
                Button(action: toggleDictation) {
                    Image(systemName: dictation.isRecording ? "stop.fill" : "mic.fill")
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(.white)
                        .frame(width: 44, height: 44)
                        .background(dictation.isRecording ? Color.red : Theme.Palette.amberDeep, in: Circle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(dictation.isRecording ? "Stop dictation" : "Dictate")
            }
            HStack {
                if reachedMax {
                    Text("Max \(maxEntries) reached — Continue to keep going.")
                        .font(Theme.Typography.meta)
                        .foregroundStyle(Theme.Palette.muted)
                }
                Spacer()
                Button(action: search) {
                    if isSearching {
                        ProgressView().controlSize(.small)
                    } else {
                        Text(input.contains(".") || input.hasPrefix("@") ? "Add directly" : "Find Substacks")
                    }
                }
                .buttonStyle(.amberFilled)
                .disabled(searchDisabled)
            }
        }
        .onChange(of: dictation.transcript) { _, newValue in
            // Live-update the text field while the user dictates so they can
            // see what was captured before tapping Find.
            input = newValue
        }
    }

    private var suggestionsList: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.s) {
            MetaLabel(text: "Suggestions")
            ForEach(candidates) { candidate in
                suggestionRow(candidate)
            }
        }
    }

    private func suggestionRow(_ candidate: SubstackCandidateDTO) -> some View {
        let alreadyAdded = registered.contains { $0.pubHost == candidate.pubHost }
        return EditorialCard {
            HStack(alignment: .top, spacing: Theme.Spacing.m) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(candidate.title ?? candidate.pubHost)
                        .font(Theme.Typography.subtitle)
                        .foregroundStyle(Theme.Palette.ink)
                    if let author = candidate.author, !author.isEmpty {
                        Text(author)
                            .font(Theme.Typography.meta)
                            .foregroundStyle(Theme.Palette.muted)
                    }
                    if let why = candidate.why, !why.isEmpty {
                        Text(why)
                            .font(Theme.Typography.callout)
                            .foregroundStyle(Theme.Palette.inkSoft)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Text(candidate.pubHost)
                        .font(Theme.Typography.meta)
                        .foregroundStyle(Theme.Palette.muted)
                }
                Spacer(minLength: 0)
                if alreadyAdded {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.system(size: 22))
                        .foregroundStyle(Theme.Palette.amberDeep)
                } else if addingCandidateID == candidate.id {
                    ProgressView()
                } else {
                    Button {
                        addCandidate(candidate)
                    } label: {
                        Text("Add")
                    }
                    .buttonStyle(.amberFilled)
                    .disabled(reachedMax)
                }
            }
        }
    }

    private func registeredRow(_ intent: SubstackIntentDTO) -> some View {
        EditorialCard {
            HStack(spacing: Theme.Spacing.m) {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(Theme.Palette.amberDeep)
                VStack(alignment: .leading, spacing: 2) {
                    Text(intent.pubTitle ?? intent.pubHost)
                        .font(Theme.Typography.subtitle)
                        .foregroundStyle(Theme.Palette.ink)
                    if let author = intent.pubAuthor, !author.isEmpty {
                        Text(author)
                            .font(Theme.Typography.meta)
                            .foregroundStyle(Theme.Palette.muted)
                    }
                }
                Spacer(minLength: 0)
            }
        }
    }

    private var trimmedInput: String {
        input.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var searchDisabled: Bool {
        isSearching || trimmedInput.isEmpty || reachedMax
    }

    private var reachedMax: Bool {
        registered.count >= maxEntries
    }

    private func toggleDictation() {
        if dictation.isRecording {
            dictation.stop()
        } else {
            input = ""
            Task { await dictation.start() }
        }
    }

    private func search() {
        let query = trimmedInput
        guard !query.isEmpty, !isSearching, !reachedMax else { return }
        if dictation.isRecording { dictation.stop() }
        lastError = nil

        // Short / URL-like inputs are a direct paste — go straight to intent
        // creation instead of paying for an LLM round-trip.
        if query.hasPrefix("@") || query.contains(".") && !query.contains(" ") {
            addByURL(query)
            return
        }

        isSearching = true
        hasSearched = true
        candidates = []
        Task {
            let results = await viewModel.discoverSubstacks(query: query)
            await MainActor.run {
                isSearching = false
                candidates = results
                if results.isEmpty {
                    lastError = viewModel.errorMessage
                }
            }
        }
    }

    private func addByURL(_ raw: String) {
        isSearching = true
        Task {
            let intent = await viewModel.createSubstackIntent(pubURL: raw)
            await MainActor.run {
                isSearching = false
                if let intent {
                    if !registered.contains(where: { $0.id == intent.id }) {
                        registered.append(intent)
                    }
                    input = ""
                    candidates = []
                    hasSearched = false
                } else {
                    lastError = viewModel.errorMessage ?? "Couldn't add that publication."
                }
            }
        }
    }

    private func addCandidate(_ candidate: SubstackCandidateDTO) {
        guard !reachedMax else { return }
        addingCandidateID = candidate.id
        Task {
            let intent = await viewModel.createSubstackIntent(pubURL: candidate.pubURL)
            await MainActor.run {
                addingCandidateID = nil
                if let intent {
                    if !registered.contains(where: { $0.id == intent.id }) {
                        registered.append(intent)
                    }
                } else {
                    lastError = viewModel.errorMessage ?? "Couldn't add that publication."
                }
            }
        }
    }
}

private struct OnboardingShowStep: View {
    @Binding var selected: String
    let isPaid: Bool
    let onBack: () -> Void
    let onContinue: () -> Void

    var body: some View {
        OnboardingStepShell(
            title: "Pick a show shape.",
            subtitle: "We'll use these defaults for your host setup. We recommend a 5-minute podcast to start — you can change the duration later on the Podcast tab.",
            primaryLabel: "Continue",
            primaryDisabled: false,
            onPrimary: onContinue,
            onBack: onBack
        ) {
            VStack(spacing: Theme.Spacing.m) {
                ForEach(OnboardingShowPreset.all) { preset in
                    PresetCard(
                        preset: preset,
                        isSelected: preset.id == selected,
                        isLocked: preset.requiresPaid && !isPaid,
                        onSelect: { selected = preset.id }
                    )
                }
            }
        }
    }

    private struct PresetCard: View {
        let preset: OnboardingShowPreset
        let isSelected: Bool
        let isLocked: Bool
        let onSelect: () -> Void

        var body: some View {
            Button(action: { if !isLocked { onSelect() } }) {
                EditorialCard {
                    HStack(alignment: .top, spacing: Theme.Spacing.m) {
                        VStack(alignment: .leading, spacing: 6) {
                            HStack(spacing: 8) {
                                Text(preset.name)
                                    .font(Theme.Typography.subtitle)
                                    .foregroundStyle(Theme.Palette.ink)
                                if preset.recommended {
                                    RecommendedBadge()
                                }
                                if isLocked {
                                    PaidBadge()
                                }
                            }
                            Text(preset.tagline)
                                .font(Theme.Typography.calloutStrong)
                                .foregroundStyle(Theme.Palette.muted)
                            Text(preset.description)
                                .font(Theme.Typography.callout)
                                .foregroundStyle(Theme.Palette.inkSoft)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer(minLength: 0)
                        Image(systemName: isLocked ? "lock.fill" : (isSelected ? "checkmark.circle.fill" : "circle"))
                            .font(.system(size: 22))
                            .foregroundStyle(isLocked ? Theme.Palette.muted : (isSelected ? Theme.Palette.amber : Theme.Palette.rule))
                    }
                }
                .overlay(
                    RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                        .stroke(isSelected && !isLocked ? Theme.Palette.amber : Color.clear, lineWidth: 2)
                )
                .opacity(isLocked ? 0.65 : 1)
            }
            .buttonStyle(.plain)
            .disabled(isLocked)
        }
    }
}

private struct RecommendedBadge: View {
    var body: some View {
        Text("Recommended")
            .font(Theme.Typography.meta)
            .tracking(1.2)
            .foregroundStyle(Theme.Palette.amberDeep)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(Theme.Palette.amber.opacity(0.18), in: Capsule())
            .overlay(
                Capsule().stroke(Theme.Palette.amberDeep, lineWidth: 1)
            )
    }
}

private struct PaidBadge: View {
    var body: some View {
        Text("Paid")
            .font(Theme.Typography.meta)
            .tracking(1.2)
            .foregroundStyle(Color.white)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(Theme.Palette.amberDeep, in: Capsule())
    }
}

@MainActor
private final class FeedbackDictation: ObservableObject {
    @Published private(set) var transcript: String = ""
    @Published private(set) var isRecording: Bool = false
    @Published var errorMessage: String?

    private let recognizer = SFSpeechRecognizer(locale: Locale.current) ?? SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?

    func start() async {
        errorMessage = nil
        guard let recognizer, recognizer.isAvailable else {
            errorMessage = "Dictation is unavailable on this device."
            return
        }

        let speechAuth = await requestSpeechAuthorization()
        guard speechAuth == .authorized else {
            errorMessage = "Enable Speech Recognition in Settings to dictate."
            return
        }
        let micAuth = await requestMicrophoneAuthorization()
        guard micAuth else {
            errorMessage = "Enable Microphone access in Settings to dictate."
            return
        }

        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true, options: .notifyOthersOnDeactivation)

            let newRequest = SFSpeechAudioBufferRecognitionRequest()
            newRequest.shouldReportPartialResults = true
            request = newRequest

            let inputNode = audioEngine.inputNode
            let format = inputNode.outputFormat(forBus: 0)
            inputNode.removeTap(onBus: 0)
            inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak newRequest] buffer, _ in
                newRequest?.append(buffer)
            }
            audioEngine.prepare()
            try audioEngine.start()

            isRecording = true
            transcript = ""
            task = recognizer.recognitionTask(with: newRequest) { [weak self] result, error in
                Task { @MainActor in
                    guard let self else { return }
                    if let result {
                        self.transcript = result.bestTranscription.formattedString
                        if result.isFinal {
                            self.stop()
                        }
                    }
                    if error != nil {
                        self.stop()
                    }
                }
            }
        } catch {
            errorMessage = error.localizedDescription
            cleanup()
        }
    }

    func stop() {
        guard isRecording else { return }
        request?.endAudio()
        cleanup()
    }

    func cancel() {
        task?.cancel()
        cleanup()
    }

    func reset() {
        transcript = ""
    }

    private func cleanup() {
        if audioEngine.isRunning {
            audioEngine.stop()
        }
        audioEngine.inputNode.removeTap(onBus: 0)
        request = nil
        task = nil
        isRecording = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private func requestSpeechAuthorization() async -> SFSpeechRecognizerAuthorizationStatus {
        await withCheckedContinuation { cont in
            SFSpeechRecognizer.requestAuthorization { status in
                cont.resume(returning: status)
            }
        }
    }

    private func requestMicrophoneAuthorization() async -> Bool {
        await withCheckedContinuation { cont in
            AVAudioApplication.requestRecordPermission { granted in
                cont.resume(returning: granted)
            }
        }
    }
}

@MainActor
private final class VoiceSamplePlayer: ObservableObject {
    @Published private(set) var playingVoiceID: String?
    private var player: AVPlayer?
    private var endObserver: NSObjectProtocol?

    func play(_ voice: CatalogVoiceDTO) {
        guard let urlString = voice.previewURL,
              !urlString.isEmpty,
              let url = URL(string: urlString) else { return }

        // Duck other audio (e.g. Spotify) while the sample plays; on
        // deactivate it un-ducks automatically so the user's music resumes.
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .default, options: [.duckOthers])
        try? AVAudioSession.sharedInstance().setActive(true)

        if let observer = endObserver {
            NotificationCenter.default.removeObserver(observer)
            endObserver = nil
        }

        let item = AVPlayerItem(url: url)
        let newPlayer = AVPlayer(playerItem: item)
        endObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime,
            object: item,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.handlePlaybackEnded() }
        }

        player = newPlayer
        playingVoiceID = voice.id
        newPlayer.play()
    }

    func stop() {
        player?.pause()
        player = nil
        if let observer = endObserver {
            NotificationCenter.default.removeObserver(observer)
            endObserver = nil
        }
        playingVoiceID = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
    }

    private func handlePlaybackEnded() {
        playingVoiceID = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: [.notifyOthersOnDeactivation])
    }
}

/// Resolves the device's current location to a "City, Country" string for the
/// weather feature. Wraps CLLocationManager + CLGeocoder and exposes a small
/// state machine so the UI can show progress / errors / a denied state.
@MainActor
final class LocationResolver: NSObject, ObservableObject, CLLocationManagerDelegate {
    enum State: Equatable {
        case idle
        case requesting
        case resolved(String)
        case denied
        case error(String)
    }

    @Published private(set) var state: State = .idle

    private let manager = CLLocationManager()
    private let geocoder = CLGeocoder()

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyKilometer
    }

    /// Request a fresh location reading. Triggers the permission prompt on
    /// first call; on subsequent calls just refreshes the GPS fix.
    func resolve() {
        switch manager.authorizationStatus {
        case .notDetermined:
            state = .requesting
            manager.requestWhenInUseAuthorization()
        case .restricted, .denied:
            state = .denied
        case .authorizedWhenInUse, .authorizedAlways:
            state = .requesting
            manager.requestLocation()
        @unknown default:
            state = .error("Couldn't read location authorization")
        }
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor in
            switch status {
            case .authorizedWhenInUse, .authorizedAlways:
                if case .requesting = state { manager.requestLocation() }
            case .denied, .restricted:
                state = .denied
            default:
                break
            }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last else { return }
        Task { @MainActor in
            await reverseGeocode(location)
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        let message = error.localizedDescription
        Task { @MainActor in
            state = .error(message)
        }
    }

    @MainActor
    private func reverseGeocode(_ location: CLLocation) async {
        do {
            let placemarks = try await geocoder.reverseGeocodeLocation(location)
            guard let pm = placemarks.first else {
                state = .error("Couldn't read place name")
                return
            }
            // Prefer "City, Country"; fall back to administrativeArea (state) if
            // locality is unavailable (e.g. rural areas, some non-US locales).
            let primary = pm.locality ?? pm.subAdministrativeArea ?? pm.administrativeArea
            let parts = [primary, pm.country].compactMap { $0 }.filter { !$0.isEmpty }
            let label = parts.joined(separator: ", ")
            if label.isEmpty {
                state = .error("Couldn't read place name")
            } else {
                state = .resolved(label)
            }
        } catch {
            state = .error(error.localizedDescription)
        }
    }
}

private enum VoiceCardRole {
    case unassigned
    case anchor
    case commentator
}

private struct OnboardingVoicesStep: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @Binding var anchorVoiceID: String?
    @Binding var commentatorVoiceID: String?
    let requiresCommentator: Bool
    let onBack: () -> Void
    let onContinue: () -> Void

    @StateObject private var samplePlayer = VoiceSamplePlayer()

    /// Voice list to render. Falls back to the legacy 2-voice static list when the
    /// catalog hasn't loaded yet (e.g. cold app start) so the picker is never empty.
    private var voices: [CatalogVoiceDTO] {
        if !viewModel.catalogVoices.isEmpty { return viewModel.catalogVoices }
        return PodcastSetupView.voiceOptions.map {
            CatalogVoiceDTO(id: $0.id, name: $0.name, gender: "neutral", description: "", previewURL: nil)
        }
    }

    private var continueDisabled: Bool {
        if viewModel.isLoading { return true }
        guard let anchor = anchorVoiceID, !anchor.isEmpty else { return true }
        if requiresCommentator {
            guard let commentator = commentatorVoiceID, commentator != anchor else { return true }
        }
        return false
    }

    private var subtitle: String {
        if requiresCommentator {
            return "Your Anchor leads, your Commenter reacts. Tap a voice to make them Commenter, or tap your Commenter to swap roles. Change either later on the Podcast tab."
        }
        return "Tap a voice to set them as Anchor. A different guest voice cycles in each episode. Change the anchor anytime on the Podcast tab."
    }

    var body: some View {
        OnboardingStepShell(
            title: "Choose a voice that fits your style.",
            subtitle: subtitle,
            primaryLabel: viewModel.isLoading ? "Saving…" : "Continue",
            primaryDisabled: continueDisabled,
            onPrimary: onContinue,
            onBack: onBack
        ) {
            VStack(spacing: Theme.Spacing.m) {
                ForEach(voices) { voice in
                    VoiceChoiceCard(
                        voice: voice,
                        role: role(for: voice.id),
                        isPlaying: samplePlayer.playingVoiceID == voice.id,
                        onCycle: { cycleRole(for: voice) },
                        onPreview: { samplePlayer.play(voice) }
                    )
                }
            }
            .onAppear { applyDefaultsIfEmpty() }
            .onChange(of: viewModel.catalogVoices) { _, _ in applyDefaultsIfEmpty() }
            .onChange(of: requiresCommentator) { _, needsCommentator in
                if !needsCommentator { commentatorVoiceID = nil }
            }
            .onDisappear { samplePlayer.stop() }
        }
    }

    private func role(for id: String) -> VoiceCardRole {
        if id == anchorVoiceID { return .anchor }
        if requiresCommentator, id == commentatorVoiceID { return .commentator }
        return .unassigned
    }

    /// Tap-to-assign logic. Anchor is always pre-filled by `applyDefaultsIfEmpty`,
    /// so tapping the anchor is a no-op (use the explicit play button to preview).
    /// - two_hosts:      tap unassigned → becomes Commenter (replacing the current one);
    ///                   tap Commenter  → swaps roles with Anchor.
    /// - rotating_guest: tap any non-anchor voice → becomes Anchor.
    private func cycleRole(for voice: CatalogVoiceDTO) {
        let id = voice.id
        let currentRole = role(for: id)
        guard currentRole != .anchor else { return }

        if requiresCommentator {
            if currentRole == .commentator {
                commentatorVoiceID = anchorVoiceID
                anchorVoiceID = id
            } else {
                commentatorVoiceID = id
            }
        } else {
            anchorVoiceID = id
        }
    }

    /// Pre-fill an anchor (and commentator if needed) on first appearance so a
    /// user who taps Continue without touching anything gets a valid setup.
    private func applyDefaultsIfEmpty() {
        let available = voices.map(\.id)
        guard !available.isEmpty else { return }
        if anchorVoiceID == nil {
            anchorVoiceID = viewModel.profile?.voiceID.flatMap { available.contains($0) ? $0 : nil } ?? available.first
        }
        if requiresCommentator, commentatorVoiceID == nil {
            commentatorVoiceID = available.first(where: { $0 != anchorVoiceID }) ?? available.last
        }
    }
}

private struct VoiceChoiceCard: View {
    let voice: CatalogVoiceDTO
    let role: VoiceCardRole
    let isPlaying: Bool
    let onCycle: () -> Void
    let onPreview: () -> Void

    private var isSelected: Bool { role != .unassigned }
    private var canPreview: Bool { (voice.previewURL?.isEmpty == false) }

    var body: some View {
        EditorialCard {
            HStack(alignment: .top, spacing: Theme.Spacing.m) {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 8) {
                        Text(voice.name)
                            .font(Theme.Typography.subtitle)
                            .foregroundStyle(Theme.Palette.ink)
                        if let badge = roleBadgeText {
                            VoiceRoleBadge(text: badge)
                        }
                    }
                    if !voice.description.isEmpty {
                        Text(voice.description)
                            .font(Theme.Typography.callout)
                            .foregroundStyle(Theme.Palette.inkSoft)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    if canPreview {
                        Button(action: onPreview) {
                            HStack(spacing: 4) {
                                Image(systemName: isPlaying ? "speaker.wave.2.fill" : "play.circle.fill")
                                    .font(.system(size: 14, weight: .semibold))
                                Text(isPlaying ? "Playing…" : "Hear a sample")
                                    .font(Theme.Typography.calloutStrong)
                            }
                            .foregroundStyle(Theme.Palette.amberDeep)
                            .padding(.top, 2)
                        }
                        .buttonStyle(.plain)
                    }
                }
                Spacer(minLength: 0)
                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 22))
                    .foregroundStyle(isSelected ? Theme.Palette.amber : Theme.Palette.rule)
            }
        }
        .overlay(
            RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                .stroke(isSelected ? Theme.Palette.amber : Color.clear, lineWidth: 2)
        )
        .contentShape(Rectangle())
        .onTapGesture { onCycle() }
    }

    private var roleBadgeText: String? {
        switch role {
        case .anchor: return "Anchor"
        case .commentator: return "Commentator"
        case .unassigned: return nil
        }
    }
}

private struct VoiceRoleBadge: View {
    let text: String
    var body: some View {
        Text(text)
            .font(Theme.Typography.meta)
            .tracking(1.2)
            .foregroundStyle(Color.white)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(Theme.Palette.amber, in: Capsule())
    }
}

private struct OnboardingScheduleStep: View {
    @Binding var selectedWeekdays: Set<String>
    @Binding var deliveryTime: Date
    let maxDeliveryDays: Int
    let onBack: () -> Void
    let onContinue: () -> Void

    static let canonicalWeekdayOrder = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    private static let dayInitials = ["M", "T", "W", "T", "F", "S", "S"]

    static func defaultDeliveryTime() -> Date {
        var components = Calendar.current.dateComponents([.year, .month, .day], from: Date())
        components.hour = 7
        components.minute = 0
        return Calendar.current.date(from: components) ?? Date()
    }

    static func formattedHHmm(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: date)
    }

    /// Parse an "HH:mm" string into a Date on today's calendar day, for seeding
    /// the time picker from the user's stored schedule. Returns nil on bad input.
    static func parseHHmm(_ value: String?) -> Date? {
        guard let value, !value.isEmpty else { return nil }
        let parts = value.split(separator: ":")
        guard parts.count == 2,
              let hour = Int(parts[0]),
              let minute = Int(parts[1]),
              (0...23).contains(hour),
              (0...59).contains(minute)
        else { return nil }
        var components = Calendar.current.dateComponents([.year, .month, .day], from: Date())
        components.hour = hour
        components.minute = minute
        return Calendar.current.date(from: components)
    }

    private var continueDisabled: Bool {
        selectedWeekdays.isEmpty || selectedWeekdays.count > maxDeliveryDays
    }

    var body: some View {
        OnboardingStepShell(
            title: "When should it land?",
            subtitle: "Pick the days you want a new episode and the time it should arrive (in your device's timezone).",
            primaryLabel: "Continue",
            primaryDisabled: continueDisabled,
            onPrimary: onContinue,
            onBack: onBack
        ) {
            VStack(alignment: .leading, spacing: Theme.Spacing.l) {
                shortcutsRow
                daysSection
                timeSection
                if selectedWeekdays.count > maxDeliveryDays {
                    Text("Your plan allows up to \(maxDeliveryDays) delivery days. Deselect a few or upgrade.")
                        .font(Theme.Typography.callout)
                        .foregroundStyle(Theme.Palette.amberDeep)
                }
            }
        }
    }

    @ViewBuilder
    private var shortcutsRow: some View {
        HStack(spacing: Theme.Spacing.s) {
            shortcut(label: "Daily", days: Set(Self.canonicalWeekdayOrder))
            shortcut(label: "Weekdays", days: Set(Self.canonicalWeekdayOrder.prefix(5)))
            shortcut(label: "Mondays", days: ["monday"])
        }
    }

    private func shortcut(label: String, days: Set<String>) -> some View {
        let exceedsCap = days.count > maxDeliveryDays
        let isActive = selectedWeekdays == days
        return Button {
            if !exceedsCap { selectedWeekdays = days }
        } label: {
            Text(label)
                .font(Theme.Typography.calloutStrong)
                .padding(.horizontal, Theme.Spacing.m)
                .padding(.vertical, 8)
                .background(isActive ? Theme.Palette.amber : Theme.Palette.rule.opacity(0.3), in: Capsule())
                .foregroundStyle(isActive ? Color.white : Theme.Palette.ink)
                .opacity(exceedsCap ? 0.45 : 1)
        }
        .buttonStyle(.plain)
        .disabled(exceedsCap)
    }

    @ViewBuilder
    private var daysSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.s) {
            Text("Days")
                .font(Theme.Typography.calloutStrong)
                .foregroundStyle(Theme.Palette.muted)
            HStack(spacing: 8) {
                ForEach(Array(Self.canonicalWeekdayOrder.enumerated()), id: \.offset) { idx, day in
                    let isSelected = selectedWeekdays.contains(day)
                    Button {
                        if isSelected {
                            selectedWeekdays.remove(day)
                        } else {
                            selectedWeekdays.insert(day)
                        }
                    } label: {
                        Text(Self.dayInitials[idx])
                            .font(Theme.Typography.subtitle)
                            .frame(width: 36, height: 36)
                            .background(isSelected ? Theme.Palette.amber : Color.clear, in: Circle())
                            .foregroundStyle(isSelected ? Color.white : Theme.Palette.ink)
                            .overlay(
                                Circle().stroke(isSelected ? Theme.Palette.amber : Theme.Palette.rule, lineWidth: 1.5)
                            )
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    @ViewBuilder
    private var timeSection: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.s) {
            Text("Time")
                .font(Theme.Typography.calloutStrong)
                .foregroundStyle(Theme.Palette.muted)
            DatePicker(
                "",
                selection: $deliveryTime,
                displayedComponents: .hourAndMinute
            )
            .datePickerStyle(.compact)
            .labelsHidden()
            .tint(Theme.Palette.amberDeep)
        }
    }
}

/// Time-based progress bar for episode generation. The backend doesn't expose a
/// real percentage, so we anchor to the typical 3–5 min generation window, fill
/// linearly toward `cap`, and snap to 100% the moment `isGenerating` flips false.
private struct GenerationProgressBar: View {
    let isGenerating: Bool
    let expectedDuration: TimeInterval

    @State private var startedAt: Date? = nil
    @State private var didComplete: Bool = false

    private let cap: Double = 0.95

    init(isGenerating: Bool, expectedDuration: TimeInterval = 240) {
        self.isGenerating = isGenerating
        self.expectedDuration = expectedDuration
    }

    /// Only render once a run has actually been tracked (started, or completed).
    /// Avoids showing a misleading 0% bar when the view appears in a state where
    /// generation never kicked off (e.g. the Done step opened without a backend
    /// run, or before `.task` triggers `generateNow()`).
    private var hasTrackedRun: Bool {
        startedAt != nil || didComplete
    }

    var body: some View {
        Group {
            if hasTrackedRun {
                TimelineView(.periodic(from: .now, by: 0.5)) { context in
                    let p = currentProgress(at: context.date)
                    VStack(alignment: .leading, spacing: 6) {
                        ProgressView(value: p)
                            .tint(Theme.Palette.amber)
                            .animation(.easeOut(duration: 0.5), value: p)
                        HStack {
                            Text(statusText)
                                .font(Theme.Typography.meta)
                                .foregroundStyle(Theme.Palette.muted)
                            Spacer()
                            Text("\(Int((p * 100).rounded()))%")
                                .font(Theme.Typography.meta)
                                .foregroundStyle(Theme.Palette.muted)
                                .monospacedDigit()
                        }
                    }
                }
            }
        }
        .onAppear { sync(active: isGenerating) }
        .onChange(of: isGenerating) { _, active in sync(active: active) }
    }

    private func currentProgress(at now: Date) -> Double {
        if didComplete { return 1.0 }
        guard let start = startedAt else { return 0 }
        let elapsed = now.timeIntervalSince(start)
        return min(cap, elapsed / expectedDuration)
    }

    private var statusText: String {
        if didComplete { return "Episode ready" }
        if isGenerating { return "Generating…" }
        return ""
    }

    private func sync(active: Bool) {
        if active {
            if startedAt == nil {
                startedAt = Date()
                didComplete = false
            }
        } else if startedAt != nil {
            withAnimation(.easeOut(duration: 0.5)) {
                didComplete = true
            }
            startedAt = nil
        }
    }
}

private struct OnboardingAliasStep: View {
    @EnvironmentObject private var viewModel: AppViewModel
    let onFinish: () -> Void
    @State private var didTriggerGeneration = false

    var body: some View {
        OnboardingStepShell(
            title: "One more thing.",
            subtitle: "We made you your own private inbound address. Forward any newsletter to it and the next episode picks it up automatically.",
            primaryLabel: "Go to dashboard",
            primaryDisabled: false,
            onPrimary: onFinish,
            onBack: nil
        ) {
            VStack(spacing: Theme.Spacing.m) {
                aliasCard
                generationCard
                Button(action: openInApplePodcasts) {
                    Label("Open Apple Podcasts", systemImage: "headphones")
                }
                .buttonStyle(.amberFilled)
                .disabled(viewModel.feed?.feedURL == nil)
            }
        }
        .task {
            guard !didTriggerGeneration else { return }
            didTriggerGeneration = true
            await viewModel.generateNow()
        }
    }

    @ViewBuilder
    private var aliasCard: some View {
        if let alias = viewModel.user?.inboundAddress, !alias.isEmpty {
            EditorialCard {
                VStack(alignment: .leading, spacing: 6) {
                    MetaLabel(text: "Your private inbound address")
                    Text(alias)
                        .font(Theme.Typography.title)
                        .foregroundStyle(Theme.Palette.amberDeep)
                        .textSelection(.enabled)
                        .accessibilityLabel("Inbound email address")
                    Text("Tap and hold to copy. Forward newsletters here, or use this address when you sign up for new ones.")
                        .font(Theme.Typography.callout)
                        .foregroundStyle(Theme.Palette.inkSoft)
                    HStack(spacing: Theme.Spacing.m) {
                        ShareLink(item: alias) {
                            Label("Share", systemImage: "square.and.arrow.up")
                                .font(Theme.Typography.calloutStrong)
                                .foregroundStyle(Theme.Palette.amberDeep)
                        }
                        Button {
                            UIPasteboard.general.string = alias
                        } label: {
                            Label("Copy", systemImage: "doc.on.doc")
                                .font(Theme.Typography.calloutStrong)
                                .foregroundStyle(Theme.Palette.amberDeep)
                        }
                    }
                    .padding(.top, 4)
                }
            }
        } else {
            EditorialCard {
                Text("Your private inbound address will appear under Sources once setup finishes.")
                    .font(Theme.Typography.body)
                    .foregroundStyle(Theme.Palette.inkSoft)
            }
        }
    }

    private var generationCard: some View {
        EditorialCard {
            VStack(alignment: .leading, spacing: Theme.Spacing.s) {
                HStack(spacing: Theme.Spacing.m) {
                    Image(systemName: viewModel.isGenerating ? "wand.and.stars" : "checkmark.seal.fill")
                        .foregroundStyle(Theme.Palette.amberDeep)
                        .font(.system(size: 22, weight: .semibold))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(viewModel.isGenerating ? "Generating your first episode…" : "Episode ready")
                            .font(Theme.Typography.subtitle)
                            .foregroundStyle(Theme.Palette.ink)
                        Text("You can close this and come back later — usually 3–5 minutes.")
                            .font(Theme.Typography.callout)
                            .foregroundStyle(Theme.Palette.inkSoft)
                    }
                    Spacer(minLength: 0)
                }
                GenerationProgressBar(isGenerating: viewModel.isGenerating)
            }
        }
    }

    private func openInApplePodcasts() {
        guard let urlString = viewModel.feed?.feedURL,
              let url = URL(string: urlString),
              let host = url.host else {
            onFinish()
            return
        }
        var components = URLComponents()
        components.scheme = "podcast"
        components.host = host
        components.path = url.path
        if let podcastURL = components.url {
            UIApplication.shared.open(podcastURL) { ok in
                if !ok { UIApplication.shared.open(url) }
            }
        }
        onFinish()
    }
}

// MARK: - Library

struct LibraryView: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.Spacing.l) {
                if viewModel.isLoadingEpisodes && viewModel.libraryEpisodes.isEmpty {
                    HStack {
                        Spacer()
                        ProgressView().tint(Theme.Palette.amberDeep)
                        Spacer()
                    }
                    .padding(.top, Theme.Spacing.xl)
                } else if viewModel.libraryEpisodes.isEmpty {
                    EditorialCard {
                        MetaLabel(text: "Nothing here yet")
                        Text("Your episodes will appear here once they're generated.")
                            .font(Theme.Typography.body)
                            .foregroundStyle(Theme.Palette.inkSoft)
                    }
                } else {
                    ForEach(viewModel.libraryEpisodes) { episode in
                        LibraryEpisodeRow(episode: episode)
                    }
                }
            }
            .padding(.horizontal, Theme.Spacing.l)
            .padding(.top, Theme.Spacing.s)
            .padding(.bottom, Theme.Spacing.xl)
        }
        .navigationTitle("Library")
        .navigationBarTitleDisplayMode(.inline)
        .editorialBackground()
        .task {
            if viewModel.libraryEpisodes.isEmpty {
                await viewModel.loadEpisodes()
            }
        }
        .refreshable {
            await viewModel.loadEpisodes()
        }
    }
}

private struct LibraryEpisodeRow: View {
    @EnvironmentObject private var viewModel: AppViewModel
    let episode: LibraryEpisodeDTO
    @State private var isTranscriptExpanded = false

    private static let dateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .none
        return formatter
    }()

    var body: some View {
        EditorialCard {
            MetaLabel(text: dateLabel)
            Text(episode.title)
                .font(Theme.Typography.title)
                .foregroundStyle(Theme.Palette.ink)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: Theme.Spacing.m) {
                if let duration = episode.durationSeconds {
                    Label(formatDuration(duration), systemImage: "clock")
                }
                Label("\(episode.processedItemCount) items", systemImage: "doc.text")
            }
            .font(Theme.Typography.callout)
            .foregroundStyle(Theme.Palette.muted)

            if !episode.sourceItemRefs.isEmpty {
                EditorialDivider()
                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    Text("Sources")
                        .font(Theme.Typography.meta)
                        .tracking(1.2)
                        .foregroundStyle(Theme.Palette.muted)
                    ForEach(uniqueSourceNames, id: \.self) { name in
                        HStack(alignment: .top, spacing: Theme.Spacing.s) {
                            Circle()
                                .fill(Theme.Palette.amber)
                                .frame(width: 6, height: 6)
                                .padding(.top, 6)
                            Text(name)
                                .font(Theme.Typography.callout)
                                .foregroundStyle(Theme.Palette.inkSoft)
                            Spacer(minLength: 0)
                        }
                    }
                }
            }

            if let transcript = episode.transcriptText, !transcript.isEmpty {
                EditorialDivider()
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) { isTranscriptExpanded.toggle() }
                } label: {
                    HStack {
                        Text("Transcript")
                            .font(Theme.Typography.calloutStrong)
                            .foregroundStyle(Theme.Palette.amberDeep)
                        Spacer()
                        Image(systemName: isTranscriptExpanded ? "chevron.up" : "chevron.down")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(Theme.Palette.amberDeep)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)

                if isTranscriptExpanded {
                    Text(transcript)
                        .font(Theme.Typography.callout)
                        .foregroundStyle(Theme.Palette.inkSoft)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                }
            }

            EditorialDivider()
            Button {
                openInApplePodcasts()
            } label: {
                Label("Open in Apple Podcasts", systemImage: "play.fill")
            }
            .buttonStyle(.amberOutlined)
            .disabled(viewModel.feed?.feedURL == nil)
        }
    }

    private var dateLabel: String {
        Self.dateFormatter.string(from: episode.publishedAt)
    }

    private var uniqueSourceNames: [String] {
        var seen = Set<String>()
        var ordered: [String] = []
        for ref in episode.sourceItemRefs {
            if seen.insert(ref.sourceName).inserted {
                ordered.append(ref.sourceName)
            }
        }
        return ordered
    }

    private func formatDuration(_ seconds: Int) -> String {
        let minutes = max(1, Int((Double(seconds) / 60.0).rounded()))
        return "\(minutes) min"
    }

    private func openInApplePodcasts() {
        guard let urlString = viewModel.feed?.feedURL,
              let url = URL(string: urlString),
              let host = url.host else { return }
        var components = URLComponents()
        components.scheme = "podcast"
        components.host = host
        components.path = url.path
        if let podcastURL = components.url {
            UIApplication.shared.open(podcastURL) { ok in
                if !ok { UIApplication.shared.open(url) }
            }
        }
    }
}

// MARK: - Swipe Deck (Tune Your Pod)

struct SwipeDeckView: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @Environment(\.dismiss) private var dismiss

    @State private var cards: [SwipeDeckCardDTO] = []
    @State private var isLoading: Bool = true
    @State private var loadError: String?

    var body: some View {
        NavigationStack {
            ZStack {
                Theme.Palette.cream.ignoresSafeArea()
                content
            }
            .navigationTitle("Tune your pod")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                        .foregroundStyle(Theme.Palette.amberDeep)
                }
            }
        }
        .task { await loadInitialDeck() }
    }

    @ViewBuilder
    private var content: some View {
        if isLoading {
            ProgressView()
                .controlSize(.large)
                .tint(Theme.Palette.amberDeep)
        } else if let loadError {
            SwipeDeckErrorState(message: loadError) {
                Task { await loadInitialDeck() }
            }
        } else if cards.isEmpty {
            SwipeDeckEmptyState {
                Task { await loadInitialDeck() }
            }
        } else {
            SwipeDeckCardStack(cards: $cards) { card, direction in
                Task { await viewModel.submitSwipe(card: card, direction: direction) }
            }
        }
    }

    private func loadInitialDeck() async {
        isLoading = true
        loadError = nil
        let fresh = await viewModel.fetchRecentSwipeDeck()
        if fresh.isEmpty, let error = viewModel.errorMessage {
            loadError = error
        } else {
            cards = fresh
        }
        isLoading = false
    }
}

private struct SwipeDeckCardStack: View {
    @Binding var cards: [SwipeDeckCardDTO]
    let onSwipe: (SwipeDeckCardDTO, Int) -> Void

    private let stackDepth = 3

    var body: some View {
        VStack(spacing: Theme.Spacing.l) {
            ZStack {
                ForEach(Array(visibleCards.reversed())) { card in
                    if let topCard = cards.first, card.id == topCard.id {
                        SwipeDeckCardView(card: card) { direction in
                            onSwipe(card, direction)
                            removeTopCard()
                        }
                        .transition(.identity)
                    } else {
                        SwipeDeckBackgroundCard(card: card, depth: stackOffset(for: card))
                            .allowsHitTesting(false)
                            .transition(.identity)
                    }
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.horizontal, Theme.Spacing.l)
            .padding(.top, Theme.Spacing.m)

            SwipeDeckActionBar(
                onPass: { commitSwipe(direction: -1) },
                onLike: { commitSwipe(direction: 1) }
            )
            .padding(.horizontal, Theme.Spacing.l)
            .padding(.bottom, Theme.Spacing.s)
        }
    }

    private var visibleCards: [SwipeDeckCardDTO] {
        Array(cards.prefix(stackDepth))
    }

    private func stackOffset(for card: SwipeDeckCardDTO) -> Int {
        guard let index = cards.firstIndex(of: card) else { return 0 }
        return index
    }

    private func commitSwipe(direction: Int) {
        guard let top = cards.first else { return }
        onSwipe(top, direction)
        removeTopCard()
    }

    private func removeTopCard() {
        guard !cards.isEmpty else { return }
        withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
            _ = cards.removeFirst()
        }
    }
}

private struct SwipeDeckCardView: View {
    let card: SwipeDeckCardDTO
    let onCommit: (Int) -> Void

    @State private var dragOffset: CGSize = .zero
    @State private var isFlying: Bool = false

    private let swipeThreshold: CGFloat = 110

    var body: some View {
        SwipeCardChrome(card: card)
            .offset(dragOffset)
            .rotationEffect(.degrees(rotationDegrees))
            .overlay(alignment: .topLeading) {
                SwipeDecisionLabel(text: "MORE LIKE THIS", color: .green, opacity: likeOpacity)
                    .padding(Theme.Spacing.l)
            }
            .overlay(alignment: .topTrailing) {
                SwipeDecisionLabel(text: "PASS", color: .red, opacity: passOpacity)
                    .padding(Theme.Spacing.l)
            }
            .gesture(
                DragGesture()
                    .onChanged { value in
                        guard !isFlying else { return }
                        dragOffset = value.translation
                    }
                    .onEnded { value in
                        guard !isFlying else { return }
                        let horizontal = value.translation.width
                        if abs(horizontal) > swipeThreshold {
                            commit(direction: horizontal > 0 ? 1 : -1)
                        } else {
                            withAnimation(.spring(response: 0.35, dampingFraction: 0.7)) {
                                dragOffset = .zero
                            }
                        }
                    }
            )
    }

    private var rotationDegrees: Double {
        let normalized = Double(dragOffset.width / 18)
        return max(-15, min(15, normalized))
    }

    private var likeOpacity: Double {
        max(0, min(1, Double(dragOffset.width / swipeThreshold)))
    }

    private var passOpacity: Double {
        max(0, min(1, Double(-dragOffset.width / swipeThreshold)))
    }

    private func commit(direction: Int) {
        isFlying = true
        let flyDistance: CGFloat = 600
        withAnimation(.easeOut(duration: 0.25)) {
            dragOffset = CGSize(width: CGFloat(direction) * flyDistance, height: dragOffset.height)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            onCommit(direction)
        }
    }
}

private struct SwipeCardChrome: View {
    let card: SwipeDeckCardDTO

    var body: some View {
        EditorialCard {
            MetaLabel(text: card.sourceName)
            Text(card.title)
                .font(Theme.Typography.title)
                .foregroundStyle(Theme.Palette.ink)
                .fixedSize(horizontal: false, vertical: true)
                .lineLimit(3)
            Text(card.displaySummary)
                .font(Theme.Typography.callout)
                .foregroundStyle(Theme.Palette.inkSoft)
                .lineLimit(5)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            HStack(spacing: Theme.Spacing.s) {
                Image(systemName: "calendar")
                Text(SwipeCardChrome.dateFormatter.string(from: card.publishedAt))
                Spacer()
                if let url = URL(string: card.link) {
                    Link(destination: url) {
                        HStack(spacing: 4) {
                            Text("Read")
                            Image(systemName: "arrow.up.right")
                        }
                        .font(Theme.Typography.calloutStrong)
                        .foregroundStyle(Theme.Palette.amberDeep)
                    }
                }
            }
            .font(Theme.Typography.callout)
            .foregroundStyle(Theme.Palette.muted)
        }
        .frame(minHeight: 320)
    }

    private static let dateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .none
        return formatter
    }()
}

private struct SwipeDeckBackgroundCard: View {
    let card: SwipeDeckCardDTO
    let depth: Int

    var body: some View {
        SwipeCardChrome(card: card)
            .scaleEffect(scale)
            .offset(y: yOffset)
            .opacity(opacity)
    }

    private var scale: CGFloat {
        max(0.85, 1.0 - CGFloat(depth) * 0.05)
    }

    private var yOffset: CGFloat {
        CGFloat(depth) * 12
    }

    private var opacity: Double {
        max(0.4, 1.0 - Double(depth) * 0.2)
    }
}

private struct SwipeDecisionLabel: View {
    let text: String
    let color: Color
    let opacity: Double

    var body: some View {
        Text(text)
            .font(.system(size: 18, weight: .heavy, design: .rounded))
            .tracking(2)
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .stroke(color, lineWidth: 3)
            )
            .foregroundStyle(color)
            .opacity(opacity)
    }
}

private struct SwipeDeckActionBar: View {
    let onPass: () -> Void
    let onLike: () -> Void

    var body: some View {
        HStack(spacing: Theme.Spacing.l) {
            Button(action: onPass) {
                Image(systemName: "xmark")
                    .font(.system(size: 22, weight: .bold))
                    .frame(width: 64, height: 64)
            }
            .buttonStyle(.amberOutlined)
            .accessibilityLabel("Pass")

            Button(action: onLike) {
                Image(systemName: "heart.fill")
                    .font(.system(size: 22, weight: .bold))
                    .frame(width: 64, height: 64)
            }
            .buttonStyle(.amberFilled)
            .accessibilityLabel("More like this")
        }
        .frame(maxWidth: .infinity)
    }
}

private struct SwipeDeckEmptyState: View {
    @EnvironmentObject private var viewModel: AppViewModel
    let onReload: () -> Void

    var body: some View {
        VStack(spacing: Theme.Spacing.m) {
            Image(systemName: "checkmark.seal")
                .font(.system(size: 44))
                .foregroundStyle(Theme.Palette.amberDeep)
            Text("All caught up")
                .font(Theme.Typography.title)
                .foregroundStyle(Theme.Palette.ink)
            Text("You've swiped through every item we've pulled in for your sources. Tap refresh to fetch the latest from your subscriptions — no podcast generation needed.")
                .font(Theme.Typography.callout)
                .foregroundStyle(Theme.Palette.inkSoft)
                .multilineTextAlignment(.center)
                .padding(.horizontal, Theme.Spacing.xl)
            Button {
                Task {
                    let ok = await viewModel.refreshCorpus()
                    if ok { onReload() }
                }
            } label: {
                if viewModel.isRefreshingCorpus {
                    HStack(spacing: 8) {
                        ProgressView().tint(.white)
                        Text("Refreshing…")
                    }
                } else {
                    Label("Refresh items", systemImage: "arrow.clockwise")
                }
            }
            .buttonStyle(.amberFilled)
            .disabled(viewModel.isRefreshingCorpus || viewModel.selectedSources.isEmpty)
            .padding(.horizontal, Theme.Spacing.xl)
            .padding(.top, Theme.Spacing.s)
        }
        .padding(Theme.Spacing.l)
    }
}

private struct SwipeDeckErrorState: View {
    let message: String
    let onRetry: () -> Void

    var body: some View {
        VStack(spacing: Theme.Spacing.m) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 44))
                .foregroundStyle(.red)
            Text("Couldn't load deck")
                .font(Theme.Typography.title)
                .foregroundStyle(Theme.Palette.ink)
            Text(message)
                .font(Theme.Typography.callout)
                .foregroundStyle(Theme.Palette.inkSoft)
                .multilineTextAlignment(.center)
                .padding(.horizontal, Theme.Spacing.xl)
            Button(action: onRetry) {
                Text("Try again")
            }
            .buttonStyle(.amberFilled)
            .padding(.horizontal, Theme.Spacing.xl)
        }
        .padding(Theme.Spacing.l)
    }
}
