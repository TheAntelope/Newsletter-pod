import AuthenticationServices
import AVFoundation
import StoreKit
import SwiftUI
import UIKit

@MainActor
final class VoicePreviewPlayer: ObservableObject {
    @Published private(set) var playingVoiceID: String?

    private var player: AVPlayer?
    private var endObserver: NSObjectProtocol?

    deinit {
        if let observer = endObserver {
            NotificationCenter.default.removeObserver(observer)
        }
    }

    func toggle(voice: CatalogVoiceDTO) {
        if playingVoiceID == voice.id {
            stop()
            return
        }
        guard let urlString = voice.previewURL,
              !urlString.isEmpty,
              let url = URL(string: urlString)
        else {
            stop()
            return
        }
        stop()
        let item = AVPlayerItem(url: url)
        let newPlayer = AVPlayer(playerItem: item)
        endObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime,
            object: item,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.stop() }
        }
        player = newPlayer
        playingVoiceID = voice.id
        newPlayer.play()
    }

    func stop() {
        player?.pause()
        player = nil
        playingVoiceID = nil
        if let observer = endObserver {
            NotificationCenter.default.removeObserver(observer)
            endObserver = nil
        }
    }
}

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
                        .font(.caption)
                        .foregroundStyle(.white)
                        .padding(10)
                        .background(Theme.Palette.amberDeep.opacity(0.95), in: Capsule())
                }
                if let savedMessage = viewModel.savedMessage {
                    Label(savedMessage, systemImage: "checkmark.circle.fill")
                        .font(.caption.weight(.semibold))
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
                    .font(Theme.Typography.display(40))
                    .foregroundStyle(Theme.Palette.ink)
                    .lineSpacing(2)
                Text("Pick your sources and format. We turn them into a private podcast you listen to in Apple Podcasts.")
                    .font(Theme.Typography.body(17))
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

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.Spacing.l) {
                    GreetingHeader()
                    HeroEpisodeCard()
                    AboutPodcastCard()
                    SourcesSummaryCard()
                    LibraryEntryCard()
                    SetupChecklistCard()
                    SendFeedbackLink()
                }
                .padding(.horizontal, Theme.Spacing.l)
                .padding(.top, Theme.Spacing.s)
                .padding(.bottom, Theme.Spacing.xl)
            }
            .navigationTitle("Your Briefing")
            .editorialBackground()
        }
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
                    .font(Theme.Typography.title(18))
                    .foregroundStyle(Theme.Palette.ink)
                Text("Titles, sources, and transcripts for everything we've made for you. Open any episode in Apple Podcasts to listen.")
                    .font(Theme.Typography.body(14))
                    .foregroundStyle(Theme.Palette.inkSoft)
            }
        }
        .buttonStyle(.plain)
        .accessibilityHint("Opens your episode library")
    }
}

private struct SendFeedbackLink: View {
    private static let address = "vincemartin1991@gmail.com"
    private static let subject = "ClawCast feedback"

    var body: some View {
        HStack {
            Spacer()
            Button {
                openMailto()
            } label: {
                Label("Send feedback", systemImage: "envelope")
                    .font(Theme.Typography.body(13).weight(.medium))
                    .foregroundStyle(Theme.Palette.muted)
            }
            .buttonStyle(.plain)
            .accessibilityHint("Opens your mail app to email feedback")
            Spacer()
        }
        .padding(.top, Theme.Spacing.s)
    }

    private func openMailto() {
        var components = URLComponents()
        components.scheme = "mailto"
        components.path = Self.address
        components.queryItems = [URLQueryItem(name: "subject", value: Self.subject)]
        if let url = components.url {
            UIApplication.shared.open(url)
        }
    }
}

private struct GreetingHeader: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        Text(greeting)
            .font(Theme.Typography.display(28))
            .foregroundStyle(Theme.Palette.ink)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityAddTraits(.isHeader)
    }

    private var greeting: String {
        guard let user = viewModel.user, user.hasFriendlyName else {
            return "good \(timeOfDay)."
        }
        return "good \(timeOfDay), \(user.firstName)."
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
                .font(Theme.Typography.title(26))
                .foregroundStyle(Theme.Palette.ink)
                .fixedSize(horizontal: false, vertical: true)

            if let latest = viewModel.feed?.latestEpisode {
                CollapsibleDescription(text: latest.description, isExpanded: $isDescriptionExpanded)

                HStack(spacing: Theme.Spacing.m) {
                    if let duration = latest.durationSeconds {
                        Label(formatDuration(duration), systemImage: "clock")
                    }
                    Label("\(latest.processedItemCount) items", systemImage: "doc.text")
                }
                .font(Theme.Typography.body(13))
                .foregroundStyle(Theme.Palette.muted)

                if let transcript = latest.transcriptText, !transcript.isEmpty {
                    CollapsibleTranscript(text: transcript)
                }
            } else if viewModel.isGenerating {
                HStack(alignment: .top, spacing: Theme.Spacing.m) {
                    ProgressView().tint(Theme.Palette.amberDeep)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Your first episode is being made.")
                            .font(Theme.Typography.body(15).weight(.semibold))
                            .foregroundStyle(Theme.Palette.ink)
                        Text("About 3–5 minutes. You can close the app and come back later — it will land in Apple Podcasts when ready.")
                            .font(Theme.Typography.body(14))
                            .foregroundStyle(Theme.Palette.inkSoft)
                    }
                }
            } else if viewModel.selectedSources.isEmpty {
                Text("Tap below for a guided setup — pick sources, choose a format, and we'll start your first episode.")
                    .font(Theme.Typography.body(15))
                    .foregroundStyle(Theme.Palette.inkSoft)

                Button {
                    viewModel.resumeOnboarding()
                } label: {
                    Label("Start guided setup", systemImage: "wand.and.stars")
                }
                .buttonStyle(.amberFilled)
            } else {
                Text("Your sources are set. Tap Generate below to make your first episode now, or wait for your scheduled delivery.")
                    .font(Theme.Typography.body(15))
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
                    UIPasteboard.general.string = viewModel.feed?.feedURL
                } label: {
                    Label("Copy feed link", systemImage: "doc.on.doc")
                }
                .buttonStyle(.amberOutlined)
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
                    .font(Theme.Typography.body(13).weight(.semibold))
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
                .font(Theme.Typography.title(15))
                .foregroundStyle(Theme.Palette.ink)
                .padding(.top, 4)
        case .bullet(let inline):
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("•")
                    .font(Theme.Typography.body(15).weight(.bold))
                    .foregroundStyle(Theme.Palette.amber)
                Text(formatted(inline))
                    .font(Theme.Typography.body(15))
                    .foregroundStyle(Theme.Palette.inkSoft)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        case .paragraph(let inline):
            Text(formatted(inline))
                .font(Theme.Typography.body(15))
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
                        .font(Theme.Typography.body(14).weight(.semibold))
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
                    .font(Theme.Typography.body(14))
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
    @State private var showScheduleEditor = false

    var body: some View {
        EditorialCard {
            MetaLabel(text: "About this podcast")
            Text(viewModel.profile?.title ?? "ClawCast")
                .font(Theme.Typography.title(20))
                .foregroundStyle(Theme.Palette.ink)

            VStack(alignment: .leading, spacing: Theme.Spacing.s) {
                infoRow(label: "Format", value: formatLabel)
                infoRow(label: "Hosts", value: hostsLabel)
                infoRow(label: "Voice", value: voiceLabel)
                infoRow(label: "Length", value: "\(viewModel.profile?.desiredDurationMinutes ?? 8) min")
                Button {
                    showScheduleEditor = true
                } label: {
                    HStack {
                        Text("Delivery")
                            .font(Theme.Typography.body(14))
                            .foregroundStyle(Theme.Palette.muted)
                        Spacer()
                        Text(deliveryLabel)
                            .font(Theme.Typography.body(14).weight(.medium))
                            .foregroundStyle(Theme.Palette.ink)
                        Image(systemName: "chevron.right")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(Theme.Palette.muted)
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .sheet(isPresented: $showScheduleEditor) {
            ScheduleEditorView()
                .environmentObject(viewModel)
        }
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
        let primary = viewModel.profile?.hostPrimaryName ?? "—"
        if let secondary = viewModel.profile?.hostSecondaryName, !secondary.isEmpty,
           viewModel.profile?.formatPreset == "two_hosts" {
            return "\(primary) & \(secondary)"
        }
        return primary
    }

    private var deliveryLabel: String {
        let days = viewModel.schedule?.weekdays.map { $0.prefix(3).capitalized }.joined(separator: ", ")
        return days?.isEmpty == false ? days! : "Not set"
    }

    private var voiceLabel: String {
        let stored = viewModel.profile?.voiceID
        let match = PodcastSetupView.voiceOptions.first { $0.id == stored }
        return match?.name ?? PodcastSetupView.voiceOptions[0].name
    }

    private func infoRow(label: String, value: String) -> some View {
        HStack {
            Text(label)
                .font(Theme.Typography.body(14))
                .foregroundStyle(Theme.Palette.muted)
            Spacer()
            Text(value)
                .font(Theme.Typography.body(14).weight(.medium))
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
                    Text("\(viewModel.selectedSources.count) / \(viewModel.entitlements?.maxSources ?? 0)")
                        .font(Theme.Typography.meta())
                        .foregroundStyle(Theme.Palette.muted)
                    Image(systemName: "chevron.right")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(Theme.Palette.muted)
                }

                if viewModel.selectedSources.isEmpty {
                    Text("Pick at least one source on the Sources tab to start receiving episodes.")
                        .font(Theme.Typography.body(15))
                        .foregroundStyle(Theme.Palette.inkSoft)
                } else {
                    VStack(alignment: .leading, spacing: Theme.Spacing.s) {
                        ForEach(viewModel.selectedSources.prefix(4)) { source in
                            HStack(spacing: Theme.Spacing.s) {
                                Circle()
                                    .fill(Theme.Palette.amber)
                                    .frame(width: 6, height: 6)
                                Text(source.name)
                                    .font(Theme.Typography.body(15))
                                    .foregroundStyle(Theme.Palette.ink)
                                    .lineLimit(1)
                                Spacer()
                                if source.isCustom {
                                    Text("Custom")
                                        .font(Theme.Typography.meta(10))
                                        .foregroundStyle(Theme.Palette.muted)
                                }
                            }
                        }
                        if viewModel.selectedSources.count > 4 {
                            Text("+\(viewModel.selectedSources.count - 4) more")
                                .font(Theme.Typography.body(13))
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

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    NewsletterEmailCard()
                }
                .listRowInsets(EdgeInsets(top: 12, leading: 0, bottom: 12, trailing: 0))
                .listRowBackground(Color.clear)

                if let address = viewModel.user?.inboundAddress, !address.isEmpty {
                    Section("Recent Newsletters") {
                        InboundItemsList()
                    }
                }

                Section("Catalog Sources") {
                    ForEach(viewModel.catalogSources) { source in
                        Toggle(source.name, isOn: Binding(
                            get: { selectedCatalogIDs.contains(source.sourceID) },
                            set: { isSelected in
                                if isSelected {
                                    selectedCatalogIDs.insert(source.sourceID)
                                } else {
                                    selectedCatalogIDs.remove(source.sourceID)
                                }
                            }
                        ))
                    }
                }

                Section("Custom RSS") {
                    ForEach(customURLs.indices, id: \.self) { index in
                        TextField("https://example.com/feed.xml", text: $customURLs[index])
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                    }

                    Button("Add another feed") {
                        customURLs.append("")
                    }
                }

                Section {
                    Button("Save sources") {
                        Task {
                            await viewModel.saveSources(
                                catalogIDs: Array(selectedCatalogIDs),
                                customURLs: customURLs
                            )
                        }
                    }
                    .buttonStyle(.amberFilled)
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
                }
            }
            .navigationTitle("Sources")
            .editorialBackground()
            .refreshable {
                await viewModel.loadInboundItems()
            }
            .task {
                await viewModel.loadInboundItems()
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
                        .font(Theme.Typography.meta())
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
                    .font(Theme.Typography.body(14))
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
                    .font(Theme.Typography.body(14))
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
                        .font(Theme.Typography.body())
                        .foregroundStyle(Theme.Palette.ink)
                    Text("Forwarded newsletters will appear here within seconds of arriving.")
                        .font(Theme.Typography.body(13))
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
                .font(Theme.Typography.body(15).weight(.semibold))
                .foregroundStyle(Theme.Palette.ink)
                .lineLimit(2)
            HStack(spacing: 6) {
                Text(item.displaySender)
                    .lineLimit(1)
                Text("·")
                Text(Self.timestampFormatter.localizedString(for: item.receivedAt, relativeTo: Date()))
            }
            .font(Theme.Typography.body(12))
            .foregroundStyle(Theme.Palette.muted)
        }
        .padding(.vertical, 4)
    }
}

// MARK: - Podcast setup

struct PodcastSetupView: View {
    static let voiceOptions: [(id: String, name: String)] = [
        ("suMMgpGbVcnihP1CcgFS", "Vinnie Chase"),
        ("RKCbSROXui75bk1SVpy8", "Demi Dreams"),
    ]

    @EnvironmentObject private var viewModel: AppViewModel
    @State private var displayName = ""
    @State private var title = ""
    @State private var formatPreset = "two_hosts"
    @State private var primaryHost = "Vinnie"
    @State private var secondaryHost = "Demi"
    @State private var guestNames = "Alex, Sam"
    @State private var durationMinutes = 3.0
    @State private var voiceID: String = PodcastSetupView.voiceOptions[0].id

    private var hostOption: (id: String, name: String) {
        PodcastSetupView.voiceOptions.first(where: { $0.id == voiceID }) ?? PodcastSetupView.voiceOptions[0]
    }

    private var commentatorOption: (id: String, name: String) {
        PodcastSetupView.voiceOptions.first(where: { $0.id != voiceID }) ?? PodcastSetupView.voiceOptions[1]
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("You") {
                    TextField("First name", text: $displayName)
                        .textContentType(.givenName)
                        .autocorrectionDisabled()
                    Button("Save name") {
                        Task {
                            let trimmed = displayName.trimmingCharacters(in: .whitespacesAndNewlines)
                            guard !trimmed.isEmpty else { return }
                            await viewModel.updateProfile(
                                displayName: trimmed,
                                timezone: viewModel.user?.timezone ?? TimeZone.current.identifier
                            )
                        }
                    }
                    .buttonStyle(.amberOutlined)
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
                    .disabled(displayName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }

                Section("Show") {
                    TextField("Podcast title", text: $title)
                    Picker("Format", selection: $formatPreset) {
                        Text("Solo host").tag("solo_host")
                        Text("Two hosts").tag("two_hosts")
                        Text("Rotating guest").tag("rotating_guest")
                    }
                    TextField("Primary host", text: $primaryHost)
                    if formatPreset == "two_hosts" {
                        TextField("Secondary host", text: $secondaryHost)
                    }
                    if formatPreset == "rotating_guest" {
                        TextField("Guest names, comma separated", text: $guestNames)
                    }
                }

                Section("Voices") {
                    HStack {
                        Text(formatPreset == "solo_host" ? "Narrator" : "Host")
                        Spacer()
                        Text(hostOption.name)
                            .foregroundStyle(Theme.Palette.muted)
                    }
                    if formatPreset != "solo_host" {
                        HStack {
                            Text("Commentator")
                            Spacer()
                            Text(commentatorOption.name)
                                .foregroundStyle(Theme.Palette.muted)
                        }
                        Button("Swap voices") {
                            voiceID = commentatorOption.id
                        }
                        .buttonStyle(.amberOutlined)
                        .listRowInsets(EdgeInsets())
                        .listRowBackground(Color.clear)
                    }
                }

                Section("Duration") {
                    Slider(
                        value: $durationMinutes,
                        in: Double(viewModel.entitlements?.minDurationMinutes ?? 3)...Double(viewModel.entitlements?.maxDurationMinutes ?? 8),
                        step: 1
                    )
                    Text("\(Int(durationMinutes)) minutes")
                        .foregroundStyle(Theme.Palette.muted)
                }

                ScheduleSection()

                Section {
                    Button("Save podcast settings") {
                        Task {
                            let guests = guestNames
                                .split(separator: ",")
                                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                                .filter { !$0.isEmpty }
                            await viewModel.savePodcastConfig(
                                title: title,
                                formatPreset: formatPreset,
                                primaryHost: primaryHost,
                                secondaryHost: formatPreset == "two_hosts" ? secondaryHost : nil,
                                guestNames: guests,
                                desiredDurationMinutes: Int(durationMinutes),
                                voiceID: voiceID
                            )
                        }
                    }
                    .buttonStyle(.amberFilled)
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
                }

            }
            .navigationTitle("Podcast Setup")
            .navigationBarTitleDisplayMode(.inline)
            .editorialBackground()
            .onAppear {
                displayName = viewModel.user?.displayName ?? ""
                title = viewModel.profile?.title ?? "ClawCast"
                formatPreset = viewModel.profile?.formatPreset ?? "two_hosts"
                primaryHost = viewModel.profile?.hostPrimaryName ?? "Vinnie"
                secondaryHost = viewModel.profile?.hostSecondaryName ?? "Demi"
                guestNames = viewModel.profile?.guestNames.joined(separator: ", ") ?? "Alex, Sam"
                durationMinutes = Double(viewModel.profile?.desiredDurationMinutes ?? 3)
                if let stored = viewModel.profile?.voiceID,
                   PodcastSetupView.voiceOptions.contains(where: { $0.id == stored }) {
                    voiceID = stored
                }
            }
        }
    }
}

struct ScheduleSection: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @State private var selectedDays: Set<String> = ["monday"]
    @State private var deliveryTime: Date = OnboardingScheduleStep.defaultDeliveryTime()

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
                            .font(Theme.Typography.title(15).weight(.semibold))
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

            Button("Save delivery schedule") {
                Task {
                    let weekdays = OnboardingScheduleStep.canonicalWeekdayOrder.filter { selectedDays.contains($0) }
                    let timezone = viewModel.user?.timezone ?? TimeZone.current.identifier
                    await viewModel.saveSchedule(
                        timezone: timezone,
                        weekdays: weekdays,
                        localTime: OnboardingScheduleStep.formattedHHmm(deliveryTime)
                    )
                }
            }
            .buttonStyle(.amberOutlined)
            .listRowInsets(EdgeInsets())
            .listRowBackground(Color.clear)
            .disabled(selectedDays.isEmpty)

            Text("Episodes are delivered in your device's timezone (\(TimeZone.current.identifier)).")
                .font(.caption)
                .foregroundStyle(Theme.Palette.muted)
        }
        .onAppear {
            selectedDays = Set(viewModel.schedule?.weekdays ?? ["monday"])
            if let parsed = OnboardingScheduleStep.parseHHmm(viewModel.schedule?.localTime) {
                deliveryTime = parsed
            }
        }
    }
}

struct ScheduleEditorView: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                ScheduleSection()
            }
            .editorialBackground()
            .navigationTitle("Delivery schedule")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                        .foregroundStyle(Theme.Palette.amberDeep)
                }
            }
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
                            .font(Theme.Typography.title(22))
                            .foregroundStyle(Theme.Palette.ink)
                        Text("Tap below to open Apple Podcasts with your private feed pre-loaded.")
                            .font(Theme.Typography.body(15))
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
                            .font(Theme.Typography.title(20))
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
                            .font(.caption)
                            .foregroundStyle(Theme.Palette.muted)
                    }

                    if let latestRun = viewModel.feed?.latestRun {
                        EditorialCard {
                            MetaLabel(text: "Latest run")
                            HStack {
                                Text(latestRun.status.capitalized)
                                    .font(Theme.Typography.title(18))
                                    .foregroundStyle(Theme.Palette.ink)
                                Spacer()
                                if latestRun.capHit {
                                    Text("Cap hit")
                                        .font(Theme.Typography.meta(10))
                                        .foregroundStyle(Theme.Palette.amberDeep)
                                        .padding(.horizontal, 8)
                                        .padding(.vertical, 4)
                                        .background(Theme.Palette.amber.opacity(0.15), in: Capsule())
                                }
                            }
                            Text(latestRun.message)
                                .font(Theme.Typography.body(14))
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

    private var headerCard: some View {
        EditorialCard {
            MetaLabel(text: viewModel.isPaid ? "You're on Paid" : "Go further")
            Text(viewModel.isPaid ? "You're all set" : "Unlock the full briefing")
                .font(Theme.Typography.title(26))
                .foregroundStyle(Theme.Palette.ink)
            Text(viewModel.isPaid
                 ? "Your subscription is active. Manage it in Settings → Apple ID → Subscriptions."
                 : "More sources, more delivery days, longer episodes. Cancel anytime.")
                .font(Theme.Typography.body(15))
                .foregroundStyle(Theme.Palette.inkSoft)
        }
    }

    private var comparisonCard: some View {
        EditorialCard {
            MetaLabel(text: "What you get")
            VStack(spacing: Theme.Spacing.s) {
                comparisonRow(label: "Sources", free: "5", paid: "15")
                EditorialDivider()
                comparisonRow(label: "Delivery days / week", free: "5", paid: "7")
                EditorialDivider()
                comparisonRow(label: "Episode length", free: "3–5 min", paid: "5–20 min")
            }
        }
    }

    private func comparisonRow(label: String, free: String, paid: String) -> some View {
        HStack {
            Text(label)
                .font(Theme.Typography.body(15))
                .foregroundStyle(Theme.Palette.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
            VStack(spacing: 2) {
                Text("Free").font(Theme.Typography.meta(10)).foregroundStyle(Theme.Palette.muted)
                Text(free).font(Theme.Typography.body(14)).foregroundStyle(Theme.Palette.inkSoft)
            }
            .frame(width: 80)
            VStack(spacing: 2) {
                Text("Paid").font(Theme.Typography.meta(10)).foregroundStyle(Theme.Palette.amberDeep)
                Text(paid).font(Theme.Typography.body(14).weight(.semibold)).foregroundStyle(Theme.Palette.ink)
            }
            .frame(width: 100)
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
                    .font(Theme.Typography.body(15))
                    .foregroundStyle(Theme.Palette.ink)
                Text("Make sure these product IDs are configured in App Store Connect:")
                    .font(Theme.Typography.body(13))
                    .foregroundStyle(Theme.Palette.muted)
                VStack(alignment: .leading, spacing: 4) {
                    Text("• \(AppConfiguration.monthlyProductID)")
                    Text("• \(AppConfiguration.annualProductID)")
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
                .font(Theme.Typography.body(14))
                .foregroundStyle(Theme.Palette.inkSoft)
        }
    }

    private var legalFooter: some View {
        VStack(spacing: 6) {
            Text("Subscriptions auto-renew until cancelled. Manage or cancel in Settings → Apple ID → Subscriptions.")
                .font(.caption)
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
            .font(.caption)
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
                        .font(Theme.Typography.title(20))
                        .foregroundStyle(Theme.Palette.ink)
                    if !product.description.isEmpty {
                        Text(product.description)
                            .font(Theme.Typography.body(13))
                            .foregroundStyle(Theme.Palette.muted)
                    }
                }
                Spacer()
                Text(product.displayPrice)
                    .font(Theme.Typography.title(18))
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
    let summary: String
    let icon: String
    let sourceIDs: [String]

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
            let preview = sources.prefix(3).map(\.name).joined(separator: ", ")
            let summary = sources.count > 3 ? "\(preview), + \(sources.count - 3) more" : preview
            return OnboardingStarterPack(
                id: topic,
                name: topic,
                summary: summary,
                icon: iconByTopic[topic] ?? "sparkles",
                sourceIDs: sources.map(\.sourceID)
            )
        }
    }
}

struct OnboardingShowPreset: Identifiable {
    let id: String
    let name: String
    let tagline: String
    let formatPreset: String
    let primaryHost: String
    let secondaryHost: String?
    let durationMinutes: Int
    let requiresPaid: Bool

    static let all: [OnboardingShowPreset] = [
        OnboardingShowPreset(
            id: "quick",
            name: "Quick brief",
            tagline: "3 minutes • solo host",
            formatPreset: "solo_host",
            primaryHost: "Vinnie",
            secondaryHost: nil,
            durationMinutes: 3,
            requiresPaid: false
        ),
        OnboardingShowPreset(
            id: "twohost",
            name: "Two-host show",
            tagline: "5 minutes • banter between two hosts",
            formatPreset: "two_hosts",
            primaryHost: "Vinnie",
            secondaryHost: "Demi",
            durationMinutes: 5,
            requiresPaid: false
        ),
        OnboardingShowPreset(
            id: "deep",
            name: "Deep dive",
            tagline: "8 minutes • two hosts, more depth",
            formatPreset: "two_hosts",
            primaryHost: "Vinnie",
            secondaryHost: "Demi",
            durationMinutes: 8,
            requiresPaid: true
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
    @State private var selectedPackIDs: Set<String> = ["tech-daily"]
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

    private var totalSteps: Int {
        // Welcome, Sources, Show, [Voices], Schedule, Done
        isSoloHostPreset ? 5 : 6
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
            OnboardingSourcesStep(
                selected: $selectedPackIDs,
                onBack: { step = 0 },
                onContinue: {
                    Task {
                        await saveSourcesFromPacks()
                        step = 2
                    }
                }
            )
        case 2:
            OnboardingShowStep(
                selected: $selectedShowPresetID,
                isPaid: viewModel.isPaid,
                onBack: { step = 1 },
                onContinue: {
                    Task {
                        await saveShowPreset()
                        // Solo-host has no commentator role, so skip the Voices step.
                        step = isSoloHostPreset ? 4 : 3
                    }
                }
            )
        case 3:
            OnboardingVoicesStep(
                anchorVoiceID: $selectedAnchorVoiceID,
                commentatorVoiceID: $selectedCommentatorVoiceID,
                onBack: { step = 2 },
                onContinue: {
                    Task {
                        await saveVoicesSelection()
                        step = 4
                    }
                }
            )
        case 4:
            OnboardingScheduleStep(
                selectedWeekdays: $selectedWeekdays,
                deliveryTime: $selectedDeliveryTime,
                maxDeliveryDays: viewModel.entitlements?.maxDeliveryDays ?? 5,
                onBack: { step = isSoloHostPreset ? 2 : 3 },
                onContinue: {
                    Task {
                        await saveSchedule()
                        step = 5
                    }
                }
            )
        default:
            OnboardingDoneStep(
                onFinish: { viewModel.completeOnboarding() }
            )
        }
    }

    private var firstName: String {
        viewModel.user?.firstName ?? ""
    }

    private func saveSourcesFromPacks() async {
        let packs = OnboardingStarterPack.packs(from: viewModel.catalogSources)
        let ids = Set(
            packs
                .filter { selectedPackIDs.contains($0.id) }
                .flatMap { $0.sourceIDs }
        )
        guard !ids.isEmpty else { return }
        await viewModel.saveSources(catalogIDs: Array(ids), customURLs: [])
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
        // The anchor's voice ID becomes the profile's primary voice. The commentator
        // is auto-derived at TTS time as "the other configured ElevenLabs voice".
        guard let anchorID = selectedAnchorVoiceID,
              let preset = OnboardingShowPreset.all.first(where: { $0.id == selectedShowPresetID }) else { return }
        let title = viewModel.profile?.title.isEmpty == false ? viewModel.profile!.title : "ClawCast"
        await viewModel.savePodcastConfig(
            title: title,
            formatPreset: preset.formatPreset,
            primaryHost: preset.primaryHost,
            secondaryHost: preset.secondaryHost,
            guestNames: [],
            desiredDurationMinutes: preset.durationMinutes,
            voiceID: anchorID
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
                            .font(Theme.Typography.display(32))
                            .foregroundStyle(Theme.Palette.ink)
                            .fixedSize(horizontal: false, vertical: true)
                        Text(subtitle)
                            .font(Theme.Typography.body(16))
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
            subtitle: "Here's how ClawCast works — tap the button below to get started.",
            primaryLabel: "Set up my podcast",
            primaryDisabled: false,
            onPrimary: onContinue,
            onBack: nil
        ) {
            VStack(alignment: .leading, spacing: Theme.Spacing.l) {
                bullet(
                    number: "1",
                    title: "Pick your sources",
                    text: "Curated topics, or pick your own feeds."
                )
                bullet(
                    number: "2",
                    title: "We generate the audio",
                    text: "Hosts read the latest items in your show."
                )
                bullet(
                    number: "3",
                    title: "Listen in Apple Podcasts",
                    text: "A private feed lands on your delivery days."
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
                .font(Theme.Typography.title(20).weight(.semibold))
                .foregroundStyle(Theme.Palette.amberDeep)
                .frame(width: 28, alignment: .leading)
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(Theme.Typography.title(17))
                    .foregroundStyle(Theme.Palette.ink)
                Text(text)
                    .font(Theme.Typography.body(14))
                    .foregroundStyle(Theme.Palette.inkSoft)
            }
        }
    }
}

private struct OnboardingSourcesStep: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @Binding var selected: Set<String>
    let onBack: () -> Void
    let onContinue: () -> Void

    var body: some View {
        let packs = OnboardingStarterPack.packs(from: viewModel.catalogSources)
        OnboardingStepShell(
            title: "Pick your topics.",
            subtitle: "Choose one or more — you can fine-tune individual feeds later on the Sources tab.",
            primaryLabel: viewModel.isLoading ? "Saving…" : "Continue",
            primaryDisabled: selected.isEmpty || viewModel.isLoading,
            onPrimary: onContinue,
            onBack: onBack
        ) {
            VStack(spacing: Theme.Spacing.m) {
                InspireMeButton(onTap: { applyInspireMe(packs: packs) })
                ForEach(packs) { pack in
                    PackCard(
                        pack: pack,
                        isSelected: selected.contains(pack.id),
                        onToggle: { toggle(pack.id) }
                    )
                }
            }
        }
    }

    private func toggle(_ id: String) {
        if selected.contains(id) {
            selected.remove(id)
        } else {
            selected.insert(id)
        }
    }

    private func applyInspireMe(packs: [OnboardingStarterPack]) {
        let availableIDs = Set(packs.map(\.id))
        let curated = OnboardingStarterPack.inspireMeTopics.filter { availableIDs.contains($0) }
        guard !curated.isEmpty else { return }
        selected = Set(curated)
    }

    private struct InspireMeButton: View {
        let onTap: () -> Void

        var body: some View {
            Button(action: onTap) {
                EditorialCard {
                    HStack(alignment: .center, spacing: Theme.Spacing.m) {
                        Image(systemName: "sparkles")
                            .font(.system(size: 22, weight: .semibold))
                            .foregroundStyle(Theme.Palette.amberDeep)
                            .frame(width: 32)
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Inspire me")
                                .font(Theme.Typography.title(18))
                                .foregroundStyle(Theme.Palette.ink)
                            Text("Our recommended mix — News, Tech, Culture, and Personal Finance.")
                                .font(Theme.Typography.body(14))
                                .foregroundStyle(Theme.Palette.inkSoft)
                                .multilineTextAlignment(.leading)
                        }
                        Spacer(minLength: 0)
                        Image(systemName: "wand.and.stars")
                            .font(.system(size: 22))
                            .foregroundStyle(Theme.Palette.amber)
                    }
                }
                .overlay(
                    RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                        .stroke(Theme.Palette.amber, lineWidth: 2)
                )
            }
            .buttonStyle(.plain)
        }
    }

    private struct PackCard: View {
        let pack: OnboardingStarterPack
        let isSelected: Bool
        let onToggle: () -> Void

        var body: some View {
            Button(action: onToggle) {
                EditorialCard {
                    HStack(alignment: .top, spacing: Theme.Spacing.m) {
                        Image(systemName: pack.icon)
                            .font(.system(size: 22, weight: .semibold))
                            .foregroundStyle(isSelected ? Theme.Palette.amberDeep : Theme.Palette.muted)
                            .frame(width: 32)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(pack.name)
                                .font(Theme.Typography.title(18))
                                .foregroundStyle(Theme.Palette.ink)
                            Text(pack.summary)
                                .font(Theme.Typography.body(14))
                                .foregroundStyle(Theme.Palette.inkSoft)
                                .multilineTextAlignment(.leading)
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
            }
            .buttonStyle(.plain)
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
            subtitle: "We'll use these defaults for your hosts and length. You can customize on the Podcast tab any time.",
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
                        VStack(alignment: .leading, spacing: 4) {
                            HStack(spacing: 8) {
                                Text(preset.name)
                                    .font(Theme.Typography.title(18))
                                    .foregroundStyle(Theme.Palette.ink)
                                if isLocked {
                                    PaidBadge()
                                }
                            }
                            Text(preset.tagline)
                                .font(Theme.Typography.body(14))
                                .foregroundStyle(Theme.Palette.inkSoft)
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

private struct PaidBadge: View {
    var body: some View {
        Text("Paid")
            .font(Theme.Typography.meta(10))
            .tracking(1.2)
            .foregroundStyle(Color.white)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(Theme.Palette.amberDeep, in: Capsule())
    }
}

private struct OnboardingVoicesStep: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @StateObject private var preview = VoicePreviewPlayer()
    @Binding var anchorVoiceID: String?
    @Binding var commentatorVoiceID: String?
    let onBack: () -> Void
    let onContinue: () -> Void

    enum Slot: String { case anchor = "Anchor", commentator = "Commentator" }

    @State private var activeSlot: Slot = .anchor

    /// Voice list to render. Falls back to the legacy 2-voice static list when the
    /// catalog hasn't loaded yet (e.g. cold app start) so the picker is never empty.
    private var voices: [CatalogVoiceDTO] {
        if !viewModel.catalogVoices.isEmpty { return viewModel.catalogVoices }
        return PodcastSetupView.voiceOptions.map {
            CatalogVoiceDTO(id: $0.id, name: $0.name, gender: "neutral", description: "", previewURL: nil)
        }
    }

    private var continueDisabled: Bool {
        anchorVoiceID == nil || commentatorVoiceID == nil || anchorVoiceID == commentatorVoiceID || viewModel.isLoading
    }

    var body: some View {
        OnboardingStepShell(
            title: "Pick your two voices.",
            subtitle: "Tap a voice to hear a sample, then assign one as the anchor and one as the commentator. You can change these any time on the Podcast tab.",
            primaryLabel: viewModel.isLoading ? "Saving…" : "Continue",
            primaryDisabled: continueDisabled,
            onPrimary: onContinue,
            onBack: onBack
        ) {
            VStack(alignment: .leading, spacing: Theme.Spacing.m) {
                slotSummary
                Divider().background(Theme.Palette.rule.opacity(0.4))
                VStack(spacing: Theme.Spacing.s) {
                    ForEach(voices) { voice in
                        voiceCard(voice)
                    }
                }
            }
            .onAppear { applyDefaultsIfEmpty() }
            .onChange(of: viewModel.catalogVoices) { _, _ in applyDefaultsIfEmpty() }
            .onDisappear { preview.stop() }
        }
    }

    /// Pre-fill anchor + commentator with the user's current profile voice and any
    /// other available voice on first appearance, so a user who taps Continue
    /// without changing anything still gets a valid two-voice setup.
    private func applyDefaultsIfEmpty() {
        let available = voices.map(\.id)
        guard !available.isEmpty else { return }
        if anchorVoiceID == nil {
            anchorVoiceID = viewModel.profile?.voiceID.flatMap { available.contains($0) ? $0 : nil } ?? available.first
        }
        if commentatorVoiceID == nil {
            commentatorVoiceID = available.first(where: { $0 != anchorVoiceID }) ?? available.last
        }
    }

    @ViewBuilder
    private var slotSummary: some View {
        HStack(spacing: Theme.Spacing.s) {
            slotChip(slot: .anchor, voiceID: anchorVoiceID)
            slotChip(slot: .commentator, voiceID: commentatorVoiceID)
        }
    }

    private func slotChip(slot: Slot, voiceID: String?) -> some View {
        let voice = voices.first(where: { $0.id == voiceID })
        let isActive = activeSlot == slot
        return Button {
            activeSlot = slot
        } label: {
            VStack(alignment: .leading, spacing: 2) {
                Text(slot.rawValue.uppercased())
                    .font(Theme.Typography.meta(11))
                    .tracking(1.1)
                    .foregroundStyle(isActive ? Theme.Palette.amberDeep : Theme.Palette.muted)
                Text(voice?.name ?? "Tap a voice below")
                    .font(Theme.Typography.body(15).weight(.semibold))
                    .foregroundStyle(Theme.Palette.ink)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, 10)
            .padding(.horizontal, Theme.Spacing.m)
            .background(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(isActive ? Theme.Palette.amber.opacity(0.18) : Theme.Palette.rule.opacity(0.18))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(isActive ? Theme.Palette.amberDeep : Color.clear, lineWidth: 1.5)
            )
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder
    private func voiceCard(_ voice: CatalogVoiceDTO) -> some View {
        let isAnchor = anchorVoiceID == voice.id
        let isCommentator = commentatorVoiceID == voice.id
        let isPlaying = preview.playingVoiceID == voice.id
        let hasPreview = !(voice.previewURL ?? "").isEmpty

        Button {
            assign(voice: voice, to: activeSlot)
            preview.toggle(voice: voice)
        } label: {
            HStack(alignment: .center, spacing: Theme.Spacing.m) {
                ZStack {
                    Circle()
                        .fill(isPlaying ? Theme.Palette.amberDeep : Theme.Palette.amber.opacity(0.25))
                        .frame(width: 36, height: 36)
                    Image(systemName: isPlaying ? "pause.fill" : "play.fill")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(isPlaying ? Color.white : Theme.Palette.amberDeep)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(voice.name)
                        .font(Theme.Typography.title(17))
                        .foregroundStyle(Theme.Palette.ink)
                    if !voice.description.isEmpty {
                        Text(voice.description)
                            .font(Theme.Typography.body(13))
                            .foregroundStyle(Theme.Palette.inkSoft)
                    } else if !hasPreview {
                        Text("Sample unavailable")
                            .font(Theme.Typography.body(12))
                            .foregroundStyle(Theme.Palette.muted)
                    }
                }
                Spacer(minLength: 0)
                if isAnchor {
                    assignmentBadge(text: "ANCHOR")
                }
                if isCommentator {
                    assignmentBadge(text: "COMMENTATOR")
                }
            }
            .padding(.vertical, Theme.Spacing.s)
            .padding(.horizontal, Theme.Spacing.m)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(Theme.Palette.creamDeep)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(
                        (isAnchor || isCommentator) ? Theme.Palette.amberDeep : Theme.Palette.rule.opacity(0.4),
                        lineWidth: (isAnchor || isCommentator) ? 1.5 : 1
                    )
            )
        }
        .buttonStyle(.plain)
    }

    private func assignmentBadge(text: String) -> some View {
        Text(text)
            .font(Theme.Typography.meta(10))
            .tracking(1.1)
            .foregroundStyle(Color.white)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(Theme.Palette.amberDeep, in: Capsule())
    }

    /// Assign the voice to the active slot. If it is already in the other slot,
    /// swap so both slots stay filled and never duplicate.
    private func assign(voice: CatalogVoiceDTO, to slot: Slot) {
        switch slot {
        case .anchor:
            if commentatorVoiceID == voice.id {
                commentatorVoiceID = anchorVoiceID
            }
            anchorVoiceID = voice.id
            activeSlot = .commentator
        case .commentator:
            if anchorVoiceID == voice.id {
                anchorVoiceID = commentatorVoiceID
            }
            commentatorVoiceID = voice.id
            activeSlot = .anchor
        }
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
                        .font(Theme.Typography.body(13))
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
                .font(Theme.Typography.body(14).weight(.semibold))
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
                .font(Theme.Typography.body(13).weight(.semibold))
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
                            .font(Theme.Typography.title(15).weight(.semibold))
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
                .font(Theme.Typography.body(13).weight(.semibold))
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

private struct OnboardingDoneStep: View {
    @EnvironmentObject private var viewModel: AppViewModel
    let onFinish: () -> Void
    @State private var didTriggerGeneration = false

    var body: some View {
        OnboardingStepShell(
            title: "You're set.",
            subtitle: "Open Apple Podcasts to subscribe — your first episode is being made now (about 3-5 minutes) and will land automatically when it's ready.",
            primaryLabel: "Open Apple Podcasts",
            primaryDisabled: viewModel.feed?.feedURL == nil,
            onPrimary: openInApplePodcasts,
            onBack: nil
        ) {
            VStack(spacing: Theme.Spacing.m) {
                EditorialCard {
                    HStack(spacing: Theme.Spacing.m) {
                        if viewModel.isGenerating {
                            ProgressView().tint(Theme.Palette.amberDeep)
                        } else {
                            Image(systemName: "wand.and.stars")
                                .foregroundStyle(Theme.Palette.amberDeep)
                                .font(.system(size: 22, weight: .semibold))
                        }
                        VStack(alignment: .leading, spacing: 2) {
                            Text(viewModel.isGenerating ? "Generating your first episode…" : "Episode requested")
                                .font(Theme.Typography.title(17))
                                .foregroundStyle(Theme.Palette.ink)
                            Text("You can close this and come back later.")
                                .font(Theme.Typography.body(13))
                                .foregroundStyle(Theme.Palette.inkSoft)
                        }
                        Spacer(minLength: 0)
                    }
                }

                Button {
                    onFinish()
                } label: {
                    Text("Go to dashboard")
                        .font(Theme.Typography.body(14).weight(.semibold))
                        .foregroundStyle(Theme.Palette.muted)
                }
                .buttonStyle(.plain)
                .padding(.top, Theme.Spacing.s)
            }
        }
        .task {
            guard !didTriggerGeneration else { return }
            didTriggerGeneration = true
            await viewModel.generateNow()
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
                            .font(Theme.Typography.body(15))
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
                .font(Theme.Typography.title(20))
                .foregroundStyle(Theme.Palette.ink)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: Theme.Spacing.m) {
                if let duration = episode.durationSeconds {
                    Label(formatDuration(duration), systemImage: "clock")
                }
                Label("\(episode.processedItemCount) items", systemImage: "doc.text")
            }
            .font(Theme.Typography.body(13))
            .foregroundStyle(Theme.Palette.muted)

            if !episode.sourceItemRefs.isEmpty {
                EditorialDivider()
                VStack(alignment: .leading, spacing: Theme.Spacing.xs) {
                    Text("Sources")
                        .font(Theme.Typography.meta(11))
                        .tracking(1.2)
                        .foregroundStyle(Theme.Palette.muted)
                    ForEach(uniqueSourceNames, id: \.self) { name in
                        HStack(alignment: .top, spacing: Theme.Spacing.s) {
                            Circle()
                                .fill(Theme.Palette.amber)
                                .frame(width: 6, height: 6)
                                .padding(.top, 6)
                            Text(name)
                                .font(Theme.Typography.body(14))
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
                            .font(Theme.Typography.body(14).weight(.semibold))
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
                        .font(Theme.Typography.body(14))
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
