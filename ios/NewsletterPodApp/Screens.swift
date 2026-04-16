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
        .overlay(alignment: .top) {
            if let errorMessage = viewModel.errorMessage {
                Text(errorMessage)
                    .font(.caption)
                    .foregroundStyle(.white)
                    .padding(10)
                    .background(Color.red.opacity(0.85), in: Capsule())
                    .padding(.top, 12)
            }
        }
    }
}

struct SignInView: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Spacer()
            Text("Build your weekly podcast feed")
                .font(.largeTitle.bold())
            Text("Choose your sources, format, duration, and delivery days. Playback happens in Apple Podcasts through your private feed.")
                .foregroundStyle(.secondary)

            SignInWithAppleButton(.signIn) { request in
                request.requestedScopes = [.email]
            } onCompletion: { result in
                Task { await handleAppleSignIn(result: result) }
            }
            .signInWithAppleButtonStyle(.black)
            .frame(height: 52)

            Spacer()
        }
        .padding(24)
    }

    private func handleAppleSignIn(result: Result<ASAuthorization, Error>) async {
        guard case .success(let authorization) = result,
              let credential = authorization.credential as? ASAuthorizationAppleIDCredential,
              let tokenData = credential.identityToken,
              let token = String(data: tokenData, encoding: .utf8) else {
            viewModel.errorMessage = "Unable to read Apple identity token."
            return
        }
        await viewModel.signIn(identityToken: token)
    }
}

struct DashboardTabView: View {
    var body: some View {
        TabView {
            DashboardView()
                .tabItem { Label("Home", systemImage: "house") }
            SourcesView()
                .tabItem { Label("Sources", systemImage: "dot.radiowaves.left.and.right") }
            PodcastSetupView()
                .tabItem { Label("Podcast", systemImage: "mic") }
            FeedAccessView()
                .tabItem { Label("Feed", systemImage: "dot.radiowaves.forward") }
            PaywallView()
                .tabItem { Label("Upgrade", systemImage: "star") }
        }
    }
}

struct DashboardView: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        NavigationStack {
            List {
                Section("Profile") {
                    LabeledContent("Name", value: viewModel.user?.displayName ?? "Not set")
                    LabeledContent("Timezone", value: viewModel.user?.timezone ?? "UTC")
                    LabeledContent("Tier", value: viewModel.subscription?.tier.capitalized ?? "Free")
                }

                Section("Delivery") {
                    LabeledContent(
                        "Days",
                        value: viewModel.schedule?.weekdays.map(\.capitalized).joined(separator: ", ") ?? "Monday"
                    )
                    LabeledContent("Window", value: "\(viewModel.schedule?.localTime ?? "07:00") to \(viewModel.schedule?.cutoffTime ?? "11:00")")
                }

                Section("Latest Episode") {
                    if let latestEpisode = viewModel.feed?.latestEpisode {
                        Text(latestEpisode.title).font(.headline)
                        Text(latestEpisode.description).lineLimit(6)
                        if latestEpisode.capHit {
                            Text("This episode hit the per-episode source cap.")
                                .foregroundStyle(.orange)
                                .font(.caption)
                        }
                    } else {
                        Text("No published episode yet.")
                            .foregroundStyle(.secondary)
                    }
                }

                Section("Limits") {
                    LabeledContent("Sources", value: "\(viewModel.selectedSources.count) / \(viewModel.entitlements?.maxSources ?? 0)")
                    LabeledContent("Weekly delivery days", value: "\(viewModel.entitlements?.maxDeliveryDays ?? 1)")
                    LabeledContent(
                        "Duration",
                        value: "\(viewModel.entitlements?.minDurationMinutes ?? 5)-\(viewModel.entitlements?.maxDurationMinutes ?? 8) min"
                    )
                }
            }
            .navigationTitle("Weekly Briefing")
        }
    }
}

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
                }
            }
            .navigationTitle("Sources")
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

struct PodcastSetupView: View {
    @EnvironmentObject private var viewModel: AppViewModel
    @State private var title = ""
    @State private var formatPreset = "two_hosts"
    @State private var primaryHost = "Elena"
    @State private var secondaryHost = "Marcus"
    @State private var guestNames = "Alex, Sam"
    @State private var durationMinutes = 8.0

    var body: some View {
        NavigationStack {
            Form {
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

                Section("Duration") {
                    Slider(
                        value: $durationMinutes,
                        in: Double(viewModel.entitlements?.minDurationMinutes ?? 5)...Double(viewModel.entitlements?.maxDurationMinutes ?? 20),
                        step: 1
                    )
                    Text("\(Int(durationMinutes)) minutes")
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
                                desiredDurationMinutes: Int(durationMinutes)
                            )
                        }
                    }
                }

                ScheduleSection()
            }
            .navigationTitle("Podcast Setup")
            .onAppear {
                title = viewModel.profile?.title ?? "My Weekly Briefing"
                formatPreset = viewModel.profile?.formatPreset ?? "two_hosts"
                primaryHost = viewModel.profile?.hostPrimaryName ?? "Elena"
                secondaryHost = viewModel.profile?.hostSecondaryName ?? "Marcus"
                guestNames = viewModel.profile?.guestNames.joined(separator: ", ") ?? "Alex, Sam"
                durationMinutes = Double(viewModel.profile?.desiredDurationMinutes ?? 8)
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

            Text("Episodes are targeted for 7:00 AM local time with retries through 11:00 AM.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .onAppear {
            timezone = viewModel.schedule?.timezone ?? TimeZone.current.identifier
            selectedDays = Set(viewModel.schedule?.weekdays ?? ["monday"])
        }
    }
}

struct FeedAccessView: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        NavigationStack {
            List {
                Section("Private Feed") {
                    Text(viewModel.feed?.feedURL ?? "No feed URL yet")
                        .textSelection(.enabled)
                    Button("Copy feed URL") {
                        UIPasteboard.general.string = viewModel.feed?.feedURL
                    }
                }

                Section("Apple Podcasts") {
                    Text("In Apple Podcasts, go to Library, tap the menu, and choose Follow a Show by URL.")
                    if let latestEpisode = viewModel.feed?.latestEpisode {
                        Text("Latest episode: \(latestEpisode.title)")
                    }
                }

                if let latestRun = viewModel.feed?.latestRun {
                    Section("Latest Run") {
                        LabeledContent("Status", value: latestRun.status)
                        Text(latestRun.message)
                        if latestRun.capHit {
                            Text("This run hit the visible item cap.")
                                .foregroundStyle(.orange)
                        }
                    }
                }
            }
            .navigationTitle("Feed Access")
        }
    }
}

struct PaywallView: View {
    @EnvironmentObject private var viewModel: AppViewModel

    var body: some View {
        NavigationStack {
            List {
                Section("Why upgrade") {
                    Text("Free: up to 5 sources, 1 delivery day, 5-8 minute episodes.")
                    Text("Paid: up to 15 sources, up to 3 delivery days, and up to 20 minute episodes.")
                }

                Section("Plans") {
                    ForEach(viewModel.purchaseManager.products, id: \.id) { product in
                        VStack(alignment: .leading, spacing: 8) {
                            Text(product.displayName).font(.headline)
                            Text(product.displayPrice).foregroundStyle(.secondary)
                            Button("Purchase \(product.displayName)") {
                                guard let userID = viewModel.user?.id else { return }
                                Task {
                                    await viewModel.purchaseManager.purchase(product: product, userID: userID)
                                    try? await viewModel.refresh()
                                }
                            }
                        }
                    }
                }

                if let message = viewModel.purchaseManager.lastPurchaseMessage {
                    Section("Purchase Status") {
                        Text(message)
                    }
                }
            }
            .navigationTitle("Upgrade")
        }
    }
}
