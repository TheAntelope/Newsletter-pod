import AuthenticationServices
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
                MetaLabel(text: "mycast")
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
            PaywallView()
                .tabItem { Label("Upgrade", systemImage: "sparkles") }
                .tag(DashboardTab.upgrade)
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
                    SetupChecklistCard()
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
        let trimmedName = (viewModel.user?.displayName ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let firstName = trimmedName
            .split(separator: " ")
            .first
            .map(String.init) ?? trimmedName
        if firstName.isEmpty {
            return "good \(timeOfDay)."
        }
        return "good \(timeOfDay), \(firstName)."
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
        viewModel.feed?.latestEpisode == nil ? "Coming Soon" : "Latest Episode"
    }

    private var episodeTitle: String {
        viewModel.feed?.latestEpisode?.title ?? "No episode yet"
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
    @State private var availableWidth: CGFloat = 0

    private let collapsedLineLimit = 4
    private let bodyFont = UIFont.systemFont(ofSize: 15)

    private var isTruncated: Bool {
        guard availableWidth > 0 else { return false }
        let constraint = CGSize(width: availableWidth, height: .greatestFiniteMagnitude)
        let bounds = (text as NSString).boundingRect(
            with: constraint,
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            attributes: [.font: bodyFont],
            context: nil
        )
        let lineCount = bounds.height / bodyFont.lineHeight
        return lineCount > CGFloat(collapsedLineLimit) + 0.1
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Spacing.s) {
            Text(text)
                .font(Theme.Typography.body(15))
                .foregroundStyle(Theme.Palette.inkSoft)
                .lineLimit(isExpanded ? nil : collapsedLineLimit)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    GeometryReader { proxy in
                        Color.clear
                            .onAppear { availableWidth = proxy.size.width }
                            .onChange(of: proxy.size.width) { _, newValue in
                                availableWidth = newValue
                            }
                    }
                )

            if isTruncated {
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        isExpanded.toggle()
                    }
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
            }
        }
    }
}

private struct AboutPodcastCard: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        EditorialCard {
            MetaLabel(text: "About this podcast")
            Text(viewModel.profile?.title ?? "mycast")
                .font(Theme.Typography.title(20))
                .foregroundStyle(Theme.Palette.ink)

            VStack(alignment: .leading, spacing: Theme.Spacing.s) {
                infoRow(label: "Format", value: formatLabel)
                infoRow(label: "Hosts", value: hostsLabel)
                infoRow(label: "Voice", value: voiceLabel)
                infoRow(label: "Length", value: "\(viewModel.profile?.desiredDurationMinutes ?? 8) min")
                infoRow(label: "Delivery", value: deliveryLabel)
            }
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
        EditorialCard {
            HStack {
                MetaLabel(text: "Your sources")
                Spacer()
                Text("\(viewModel.selectedSources.count) / \(viewModel.entitlements?.maxSources ?? 0)")
                    .font(Theme.Typography.meta())
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

// MARK: - Podcast setup

struct PodcastSetupView: View {
    static let voiceOptions: [(id: String, name: String)] = [
        ("hYjzO0gkYN6FIXTHyEpi", "Vinnie Chase"),
        ("suMMgpGbVcnihP1CcgFS", "Demi Dreams"),
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

                ScheduleSection()
            }
            .navigationTitle("Podcast Setup")
            .editorialBackground()
            .onAppear {
                displayName = viewModel.user?.displayName ?? ""
                title = viewModel.profile?.title ?? "mycast"
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
    @State private var timezone = TimeZone.current.identifier
    @State private var selectedDays: Set<String> = ["monday"]

    var body: some View {
        Section("Weekly Delivery") {
            TextField("Timezone", text: $timezone)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()

            ForEach(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"], id: \.self) { day in
                Toggle(day.capitalized, isOn: Binding(
                    get: { selectedDays.contains(day) },
                    set: { isSelected in
                        if isSelected {
                            selectedDays.insert(day)
                        } else {
                            selectedDays.remove(day)
                        }
                    }
                ))
            }

            Button("Save delivery schedule") {
                Task {
                    await viewModel.saveSchedule(
                        timezone: timezone,
                        weekdays: Array(selectedDays).sorted()
                    )
                }
            }
            .buttonStyle(.amberOutlined)
            .listRowInsets(EdgeInsets())
            .listRowBackground(Color.clear)

            Text("Episodes target 7:00 AM local time with retries through 11:00 AM.")
                .font(.caption)
                .foregroundStyle(Theme.Palette.muted)
        }
        .onAppear {
            timezone = viewModel.schedule?.timezone ?? TimeZone.current.identifier
            selectedDays = Set(viewModel.schedule?.weekdays ?? ["monday"])
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
                comparisonRow(label: "Delivery days / week", free: "1", paid: "3")
                EditorialDivider()
                comparisonRow(label: "Episode length", free: "5–8 min", paid: "up to 20 min")
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

    static let all: [OnboardingStarterPack] = [
        OnboardingStarterPack(
            id: "tech-daily",
            name: "Tech daily",
            summary: "TechCrunch, Hacker News, GeekWire.",
            icon: "bolt.fill",
            sourceIDs: ["techcrunch", "hacker-news", "geekwire-startups"]
        ),
        OnboardingStarterPack(
            id: "deep-reads",
            name: "Deep reads",
            summary: "Ars Technica, MIT Technology Review, WIRED Business.",
            icon: "book.fill",
            sourceIDs: ["ars-technica", "mit-technology-review", "wired-business"]
        ),
        OnboardingStarterPack(
            id: "strategy",
            name: "Strategy & business",
            summary: "Stratechery, WIRED Business, VentureBeat.",
            icon: "chart.line.uptrend.xyaxis",
            sourceIDs: ["stratechery", "wired-business", "venturebeat"]
        ),
        OnboardingStarterPack(
            id: "mix",
            name: "Mix it up",
            summary: "A balanced rotation across news, analysis, and deep tech.",
            icon: "sparkles",
            sourceIDs: ["hacker-news", "techcrunch", "ars-technica", "mit-technology-review"]
        ),
    ]
}

struct OnboardingShowPreset: Identifiable {
    let id: String
    let name: String
    let tagline: String
    let formatPreset: String
    let primaryHost: String
    let secondaryHost: String?
    let durationMinutes: Int

    static let all: [OnboardingShowPreset] = [
        OnboardingShowPreset(
            id: "quick",
            name: "Quick brief",
            tagline: "3 minutes • solo host",
            formatPreset: "solo_host",
            primaryHost: "Vinnie",
            secondaryHost: nil,
            durationMinutes: 3
        ),
        OnboardingShowPreset(
            id: "twohost",
            name: "Two-host show",
            tagline: "5 minutes • banter between two hosts",
            formatPreset: "two_hosts",
            primaryHost: "Vinnie",
            secondaryHost: "Demi",
            durationMinutes: 5
        ),
        OnboardingShowPreset(
            id: "deep",
            name: "Deep dive",
            tagline: "8 minutes • two hosts, more depth",
            formatPreset: "two_hosts",
            primaryHost: "Vinnie",
            secondaryHost: "Demi",
            durationMinutes: 8
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
}

struct OnboardingFlowView: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @State private var step: Int = 0
    @State private var selectedPackIDs: Set<String> = ["tech-daily"]
    @State private var selectedShowPresetID: String = "twohost"
    @State private var selectedSchedule: OnboardingScheduleChoice = .daily

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                Theme.Palette.cream.ignoresSafeArea()
                stepContent
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    OnboardingProgressDots(current: step, total: 5)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    if step < 4 {
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
                onBack: { step = 1 },
                onContinue: {
                    Task {
                        await saveShowPreset()
                        step = 3
                    }
                }
            )
        case 3:
            OnboardingScheduleStep(
                selected: $selectedSchedule,
                onBack: { step = 2 },
                onContinue: {
                    Task {
                        await saveSchedule()
                        step = 4
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
        let trimmed = (viewModel.user?.displayName ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.split(separator: " ").first.map(String.init) ?? trimmed
    }

    private func saveSourcesFromPacks() async {
        let ids = Set(
            OnboardingStarterPack.all
                .filter { selectedPackIDs.contains($0.id) }
                .flatMap { $0.sourceIDs }
        )
        guard !ids.isEmpty else { return }
        await viewModel.saveSources(catalogIDs: Array(ids), customURLs: [])
    }

    private func saveShowPreset() async {
        guard let preset = OnboardingShowPreset.all.first(where: { $0.id == selectedShowPresetID }) else { return }
        let title = (viewModel.profile?.title.isEmpty == false) ? viewModel.profile!.title : "mycast"
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

    private func saveSchedule() async {
        let timezone = viewModel.user?.timezone ?? TimeZone.current.identifier
        await viewModel.saveSchedule(timezone: timezone, weekdays: selectedSchedule.weekdays)
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
            subtitle: "Here's how mycast works — about 30 seconds, then we'll start your first episode.",
            primaryLabel: "Let's set it up",
            primaryDisabled: false,
            onPrimary: onContinue,
            onBack: nil
        ) {
            VStack(alignment: .leading, spacing: Theme.Spacing.m) {
                bullet(icon: "tray.full", title: "Pick your sources", text: "Curated packs of feeds, or pick your own.")
                bullet(icon: "waveform", title: "We generate audio", text: "Hosts read the latest items in your show.")
                bullet(icon: "antenna.radiowaves.left.and.right", title: "Listen in Apple Podcasts", text: "A private feed lands every delivery day.")
            }
        }
    }

    private var greeting: String {
        firstName.isEmpty ? "Welcome to mycast." : "Hi \(firstName) — welcome to mycast."
    }

    private func bullet(icon: String, title: String, text: String) -> some View {
        EditorialCard {
            HStack(alignment: .top, spacing: Theme.Spacing.m) {
                Image(systemName: icon)
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(Theme.Palette.amberDeep)
                    .frame(width: 32)
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
}

private struct OnboardingSourcesStep: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @Binding var selected: Set<String>
    let onBack: () -> Void
    let onContinue: () -> Void

    var body: some View {
        OnboardingStepShell(
            title: "Pick a starter pack.",
            subtitle: "Choose one or more — you can fine-tune individual feeds later on the Sources tab.",
            primaryLabel: viewModel.isLoading ? "Saving…" : "Continue",
            primaryDisabled: selected.isEmpty || viewModel.isLoading,
            onPrimary: onContinue,
            onBack: onBack
        ) {
            VStack(spacing: Theme.Spacing.m) {
                ForEach(OnboardingStarterPack.all) { pack in
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
                        onSelect: { selected = preset.id }
                    )
                }
            }
        }
    }

    private struct PresetCard: View {
        let preset: OnboardingShowPreset
        let isSelected: Bool
        let onSelect: () -> Void

        var body: some View {
            Button(action: onSelect) {
                EditorialCard {
                    HStack(alignment: .top, spacing: Theme.Spacing.m) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(preset.name)
                                .font(Theme.Typography.title(18))
                                .foregroundStyle(Theme.Palette.ink)
                            Text(preset.tagline)
                                .font(Theme.Typography.body(14))
                                .foregroundStyle(Theme.Palette.inkSoft)
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

private struct OnboardingScheduleStep: View {
    @Binding var selected: OnboardingScheduleChoice
    let onBack: () -> Void
    let onContinue: () -> Void

    var body: some View {
        OnboardingStepShell(
            title: "When should it land?",
            subtitle: "Episodes target 7:00 AM in your local timezone (\(TimeZone.current.identifier)).",
            primaryLabel: "Continue",
            primaryDisabled: false,
            onPrimary: onContinue,
            onBack: onBack
        ) {
            VStack(spacing: Theme.Spacing.s) {
                ForEach(OnboardingScheduleChoice.allCases) { choice in
                    Button {
                        selected = choice
                    } label: {
                        EditorialCard {
                            HStack {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(choice.label)
                                        .font(Theme.Typography.title(18))
                                        .foregroundStyle(Theme.Palette.ink)
                                    Text(choice.detail)
                                        .font(Theme.Typography.body(14))
                                        .foregroundStyle(Theme.Palette.inkSoft)
                                }
                                Spacer(minLength: 0)
                                Image(systemName: selected == choice ? "checkmark.circle.fill" : "circle")
                                    .font(.system(size: 22))
                                    .foregroundStyle(selected == choice ? Theme.Palette.amber : Theme.Palette.rule)
                            }
                        }
                        .overlay(
                            RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                                .stroke(selected == choice ? Theme.Palette.amber : Color.clear, lineWidth: 2)
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
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
            subtitle: "Your first episode is being made now — about 3-5 minutes. Subscribe in Apple Podcasts so it lands automatically when ready.",
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
                    UIPasteboard.general.string = viewModel.feed?.feedURL
                } label: {
                    Label("Copy feed link", systemImage: "doc.on.doc")
                }
                .buttonStyle(.amberOutlined)
                .disabled(viewModel.feed?.feedURL == nil)

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
