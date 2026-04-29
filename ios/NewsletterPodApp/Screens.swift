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
                    }
            } else {
                SignInView()
            }
        }
        .tint(Theme.Palette.amberDeep)
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
    init() {
        let appearance = UITabBarAppearance()
        appearance.configureWithOpaqueBackground()
        appearance.backgroundColor = UIColor(Theme.Palette.cream)
        UITabBar.appearance().standardAppearance = appearance
        UITabBar.appearance().scrollEdgeAppearance = appearance
    }

    var body: some View {
        TabView {
            HomeView()
                .tabItem { Label("Home", systemImage: "house.fill") }
            SourcesView()
                .tabItem { Label("Sources", systemImage: "tray.full") }
            PodcastSetupView()
                .tabItem { Label("Podcast", systemImage: "mic.fill") }
            FeedAccessView()
                .tabItem { Label("Feed", systemImage: "antenna.radiowaves.left.and.right") }
            PaywallView()
                .tabItem { Label("Upgrade", systemImage: "sparkles") }
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

    var body: some View {
        EditorialCard {
            MetaLabel(text: episodeBadge)
            Text(episodeTitle)
                .font(Theme.Typography.title(26))
                .foregroundStyle(Theme.Palette.ink)
                .fixedSize(horizontal: false, vertical: true)

            if let latest = viewModel.feed?.latestEpisode {
                Text(latest.description)
                    .font(Theme.Typography.body(15))
                    .foregroundStyle(Theme.Palette.inkSoft)
                    .lineLimit(4)

                HStack(spacing: Theme.Spacing.m) {
                    if let duration = latest.durationSeconds {
                        Label(formatDuration(duration), systemImage: "clock")
                    }
                    Label("\(latest.processedItemCount) items", systemImage: "doc.text")
                }
                .font(Theme.Typography.body(13))
                .foregroundStyle(Theme.Palette.muted)
            } else {
                Text("Once your first episode is ready, it will appear here. Configure your sources and delivery schedule to get started.")
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
                    if viewModel.isLoading {
                        HStack(spacing: 8) {
                            ProgressView().tint(Theme.Palette.amberDeep)
                            Text("Generating…")
                        }
                    } else {
                        Label("Generate episode now", systemImage: "wand.and.stars")
                    }
                }
                .buttonStyle(.amberOutlined)
                .disabled(viewModel.isLoading || viewModel.selectedSources.isEmpty)
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
                    ChecklistRow(label: "Pick at least one source", isComplete: hasSources)
                    ChecklistRow(label: "Configure your show", isComplete: hasShowConfigured)
                    ChecklistRow(label: "Set a delivery schedule", isComplete: hasSchedule)
                    ChecklistRow(label: "First episode ready", isComplete: hasEpisode)
                }
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
    @State private var deliveryTime: Date = ScheduleSection.defaultDeliveryTime

    var body: some View {
        Section("Weekly Delivery") {
            TextField("Timezone", text: $timezone)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()

            DatePicker(
                "Delivery time",
                selection: $deliveryTime,
                displayedComponents: .hourAndMinute
            )

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
                        weekdays: Array(selectedDays).sorted(),
                        localTime: ScheduleSection.formatLocalTime(deliveryTime)
                    )
                }
            }
            .buttonStyle(.amberOutlined)
            .listRowInsets(EdgeInsets())
            .listRowBackground(Color.clear)

            Text("Episodes start generating at the time you pick and retry for the next four hours.")
                .font(.caption)
                .foregroundStyle(Theme.Palette.muted)
        }
        .onAppear {
            timezone = viewModel.schedule?.timezone ?? TimeZone.current.identifier
            selectedDays = Set(viewModel.schedule?.weekdays ?? ["monday"])
            if let storedLocal = viewModel.schedule?.localTime,
               let parsed = ScheduleSection.parseLocalTime(storedLocal) {
                deliveryTime = parsed
            }
        }
    }

    private static var defaultDeliveryTime: Date {
        parseLocalTime("07:00") ?? Date()
    }

    private static func parseLocalTime(_ value: String) -> Date? {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "HH:mm"
        return formatter.date(from: value)
    }

    private static func formatLocalTime(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: date)
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
