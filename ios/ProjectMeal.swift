import SwiftUI
import UIKit

@main
struct ProjectMealApp: App {
    @AppStorage("meal.appearance") private var appearance = MealAppearance.system

    var body: some Scene {
        WindowGroup {
            MealAppearanceRoot(appearance: $appearance)
        }
    }
}

private struct MealAppearanceRoot: View {
    @Environment(\.colorScheme) private var systemScheme
    @Binding var appearance: MealAppearance

    var body: some View {
        let scheme = appearance.colorScheme ?? systemScheme
        MealTabs(appearance: $appearance)
            .tint(MealPalette.terracotta.color(for: scheme))
            .environment(\.colorScheme, scheme)
            .background(WindowAppearance(style: appearance.interfaceStyle))
    }
}

private struct MealTabs: View {
    private enum Destination: String, CaseIterable {
        case planner = "Plan"
        case week = "Week"
        case browse = "Browse"
        case profile = "Profile"

        var icon: String {
            switch self {
            case .planner: "fork.knife"
            case .week: "calendar"
            case .browse: "magnifyingglass"
            case .profile: "person.crop.circle"
            }
        }
    }

    @Binding var appearance: MealAppearance
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @AppStorage("meal.latestPlan") private var latestPlan = Data()
    @State private var selectedTab = Destination.planner

    private var plan: MealPlan? {
        try? JSONDecoder().decode(MealPlan.self, from: latestPlan)
    }

    var body: some View {
        TabView(selection: $selectedTab) {
            PlannerView(hasPlan: plan != nil, showWeek: { select(.week) }) { generated in
                var generated = generated
                generated.startsOn = Calendar.current.startOfDay(for: .now)
                if let data = try? JSONEncoder().encode(generated) {
                    latestPlan = data
                    select(.week)
                }
            }
            .tag(Destination.planner)

            ZStack {
                NavigationStack {
                    if let plan {
                        PlanView(plan: plan)
                    } else {
                        MealPage {
                            MealCard("Your week is empty", "Generate a plan to see lunches, dinners, and your shopping list here.",
                                     icon: "calendar", color: MealPalette.saffron) {
                                Button("Set up a plan") { select(.planner) }
                                    .buttonStyle(.bordered)
                            }
                        }
                        .navigationTitle("Week")
                    }
                }
                .id(plan?.id)
            }
            .tag(Destination.week)

            NavigationStack { BrowseView() }
                .tag(Destination.browse)

            ProfileView(appearance: $appearance)
                .tag(Destination.profile)
        }
        .tabViewStyle(.page(indexDisplayMode: .never))
        .safeAreaInset(edge: .bottom, spacing: 0) { tabBar }
    }

    private func select(_ destination: Destination) {
        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.28)) {
            selectedTab = destination
        }
    }

    private var tabBar: some View {
        HStack(spacing: 4) {
            ForEach(Destination.allCases, id: \.self) { destination in
                let selected = destination == selectedTab
                Button {
                    select(destination)
                } label: {
                    VStack(spacing: 4) {
                        Image(systemName: destination.icon)
                            .font(.system(size: 19, weight: .semibold))
                        Text(destination.rawValue)
                            .font(.caption2.weight(.semibold))
                    }
                    .foregroundStyle(selected ? MealPalette.terracotta : MealPalette.secondaryText)
                    .frame(maxWidth: .infinity, minHeight: 44)
                    .padding(.vertical, 2)
                    .background(selected ? MealPalette.control : MealPalette.clear, in: Capsule())
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(destination.rawValue)
                .accessibilityIdentifier("meal-tab-\(destination.rawValue)")
                .accessibilityAddTraits(selected ? .isSelected : [])
            }
        }
        .padding(4)
        .background(.regularMaterial, in: Capsule())
        .overlay { Capsule().strokeBorder(MealPalette.outline.opacity(0.45), lineWidth: 1) }
        .padding(.horizontal, 20)
        .padding(.vertical, 5)
    }
}

private enum MealAppearance: String, CaseIterable, Identifiable {
    case system = "System"
    case light = "Light"
    case dark = "OLED Dark"  // Preserve the saved value from earlier builds.

    var id: Self { self }

    var title: String { self == .dark ? "Dark" : rawValue }

    var colorScheme: ColorScheme? {
        switch self {
        case .system: nil
        case .light: .light
        case .dark: .dark
        }
    }

    var interfaceStyle: UIUserInterfaceStyle {
        switch self {
        case .system: .unspecified
        case .light: .light
        case .dark: .dark
        }
    }
}

private struct WindowAppearance: UIViewRepresentable {
    let style: UIUserInterfaceStyle

    func makeUIView(context: Context) -> AppearanceView {
        AppearanceView()
    }

    func updateUIView(_ view: AppearanceView, context: Context) {
        view.style = style
        view.applyStyle()
    }

    final class AppearanceView: UIView {
        var style: UIUserInterfaceStyle = .unspecified

        override func didMoveToWindow() {
            super.didMoveToWindow()
            applyStyle()
        }

        func applyStyle() {
            guard let window, window.overrideUserInterfaceStyle != style else { return }
            window.overrideUserInterfaceStyle = style
        }
    }
}

private extension View {
    func mealSurface() -> some View {
        scrollContentBackground(.hidden)
            .background {
                Rectangle().fill(MealPalette.canvas).ignoresSafeArea()
            }
    }

    func profileField() -> some View {
        padding(12)
            .frame(minHeight: 44)
            .background(MealPalette.control, in: RoundedRectangle(cornerRadius: 10))
    }

    func mealRows() -> some View {
        listRowBackground(Rectangle().fill(MealPalette.card))
    }
}

private enum MealAvatar: String, CaseIterable, Identifiable {
    case person = "Person"
    case chef = "Chef"
    case leaf = "Leaf"
    case flame = "Flame"

    var id: Self { self }

    var icon: String {
        switch self {
        case .person: "person.crop.circle"
        case .chef: "frying.pan"
        case .leaf: "leaf"
        case .flame: "flame"
        }
    }
}

private struct ProfileView: View {
    @AppStorage("meal.displayName") private var displayName = ""
    @AppStorage("meal.handle") private var handle = ""
    @AppStorage("meal.bio") private var bio = ""
    @AppStorage("meal.city") private var city = ""
    @AppStorage("meal.avatar") private var avatar = MealAvatar.person
    @Binding var appearance: MealAppearance

    private var cleanHandle: String {
        handle.trimmingCharacters(in: .whitespacesAndNewlines).drop(while: { $0 == "@" }).description
    }

    var body: some View {
        NavigationStack {
            MealPage {
                MealCard(displayName.isEmpty ? "Your profile" : displayName,
                         cleanHandle.isEmpty ? "Make this space yours." : "@\(cleanHandle)",
                         icon: avatar.icon, color: MealPalette.terracotta) {
                    if !city.isEmpty {
                        Label(city, systemImage: "location").font(.subheadline)
                    }
                    if !bio.isEmpty {
                        Text(bio).font(.subheadline).foregroundStyle(MealPalette.secondaryText)
                    }
                    NavigationLink {
                        editProfile
                    } label: {
                        MealLinkLabel("Edit profile", icon: "pencil")
                    }
                    .buttonStyle(.plain)
                }
                MealCard("Favorites", "Keep recipes and ingredients you want to come back to.",
                         icon: "heart", color: MealPalette.plum) {
                    NavigationLink {
                        BrowseView(favoritesOnly: true)
                    } label: {
                        MealLinkLabel("View favorites", icon: "heart")
                    }
                    .buttonStyle(.plain)
                }
                MealCard("Friends’ table", "When meal sharing is available, meals your friends share will appear here.",
                         icon: "person.2", color: MealPalette.olive) {
                    EmptyView()
                }
                MealCard("Preferences", "Choose how the app looks on this device.",
                         icon: "circle.lefthalf.filled", color: MealPalette.plum) {
                    HStack {
                        Text("Appearance").font(.subheadline.weight(.medium))
                        Spacer()
                        Picker("Appearance", selection: $appearance) {
                            ForEach(MealAppearance.allCases) { option in
                                Text(option.title).tag(option)
                            }
                        }
                        .labelsHidden()
                        .pickerStyle(.menu)
                        .accessibilityLabel("Appearance")
                        .accessibilityIdentifier("meal-appearance")
                        .accessibilityValue(appearance.title)
                    }
                    .padding(.horizontal, 12)
                    .frame(minHeight: 44)
                    .background(MealPalette.control, in: RoundedRectangle(cornerRadius: 10))
                }
                MealCard("Privacy & about", "Your profile details are stored on this device.",
                         icon: "lock", color: MealPalette.saffron) {
                    LabeledContent("Version", value: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0")
                        .font(.subheadline)
                }
            }
            .navigationTitle("Profile")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    private var editProfile: some View {
        MealPage {
            MealCard("Profile details", "Changes are saved on this device as you edit.",
                     icon: "person.crop.circle", color: MealPalette.terracotta) {
                Picker("Avatar", selection: $avatar) {
                    ForEach(MealAvatar.allCases) { option in
                        Label(option.rawValue, systemImage: option.icon).tag(option)
                    }
                }
                .pickerStyle(.menu)
                .frame(maxWidth: .infinity, alignment: .leading)
                .profileField()
                TextField("Display name", text: $displayName)
                    .textContentType(.nickname)
                    .profileField()
                TextField("Username", text: $handle)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .profileField()
                TextField("City", text: $city)
                    .textContentType(.addressCity)
                    .profileField()
                TextField("Bio", text: $bio, axis: .vertical)
                    .lineLimit(2...4)
                    .profileField()
            }
        }
        .scrollDismissesKeyboard(.interactively)
        .navigationTitle("Edit profile")
        .navigationBarTitleDisplayMode(.inline)
    }
}

private enum MealPalette {
    static let canvas = adaptive(0xF8F1E8, 0x000000)
    static let dock = adaptive(0xF8F1E8, 0x171514)
    static let card = adaptive(0xFFFDF8, 0x252322)
    static let control = adaptive(0xF5ECE1, 0x353230)
    static let outline = adaptive(0xDCCABC, 0x89817D)
    static let secondaryText = adaptive(0x62544C, 0xDEDADE)
    static let terracotta = adaptive(0x943B25, 0xFFAA89)
    static let olive = adaptive(0x48613B, 0xBDD79E)
    static let plum = adaptive(0x70476C, 0xE5B8E1)
    static let saffron = adaptive(0x805414, 0xFFCE79)

    static let primaryText = adaptive(0x211A17, 0xFFFFFF)
    static let clear = MealColor(light: 0, dark: 0, alpha: 0)

    private static func adaptive(_ light: UInt32, _ dark: UInt32) -> MealColor {
        MealColor(light: light, dark: dark)
    }
}

private struct MealColor: ShapeStyle {
    let light: UInt32
    let dark: UInt32
    var alpha = 1.0

    func resolve(in environment: EnvironmentValues) -> Color {
        color(for: environment.colorScheme)
    }

    func color(for scheme: ColorScheme) -> Color {
        let rgb = scheme == .dark ? dark : light
        return Color(red: Double((rgb >> 16) & 255) / 255,
                     green: Double((rgb >> 8) & 255) / 255,
                     blue: Double(rgb & 255) / 255, opacity: alpha)
    }

    func opacity(_ opacity: Double) -> MealColor {
        MealColor(light: light, dark: dark, alpha: alpha * opacity)
    }
}

private struct MealPage<Content: View>: View {
    @ViewBuilder let content: () -> Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16, content: content)
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
        }
        .mealSurface()
    }
}

private struct MealCard<Content: View>: View {
    let title: String
    let subtitle: String?
    let icon: String
    let color: MealColor
    let content: Content

    init(_ title: String, _ subtitle: String? = nil, icon: String, color: MealColor,
         @ViewBuilder content: () -> Content) {
        self.title = title
        self.subtitle = subtitle
        self.icon = icon
        self.color = color
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 10) {
                MealBadge(icon: icon, color: color)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(.headline).foregroundStyle(.primary)
                    if let subtitle {
                        Text(subtitle).font(.footnote).foregroundStyle(MealPalette.secondaryText)
                    }
                }
            }
            content
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(MealPalette.card, in: RoundedRectangle(cornerRadius: 18))
    }
}

private struct MealBadge: View {
    let icon: String
    let color: MealColor

    var body: some View {
        Image(systemName: icon)
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(color)
            .frame(width: 34, height: 34)
            .background(color.opacity(0.17), in: RoundedRectangle(cornerRadius: 9))
            .accessibilityHidden(true)
    }
}

private struct MealLinkLabel: View {
    let title: String
    let icon: String

    init(_ title: String, icon: String) {
        self.title = title
        self.icon = icon
    }

    var body: some View {
        HStack {
            Label(title, systemImage: icon).font(.subheadline.weight(.semibold))
            Spacer()
            Image(systemName: "chevron.right")
                .font(.caption.weight(.semibold))
                .accessibilityHidden(true)
        }
        .foregroundStyle(MealPalette.terracotta)
        .padding(.horizontal, 12)
        .frame(minHeight: 44)
        .background(MealPalette.control, in: RoundedRectangle(cornerRadius: 10))
    }
}

private struct Choice: Identifiable {
    let id: String
    let title: String
    let icon: String
    let color: MealColor
}

private func pkr(_ amount: Int) -> String {
    "PKR \(amount.formatted())"
}

private func amount(_ quantity: Int, _ unit: String) -> String {
    unit == "count" ? quantity.formatted() : "\(quantity.formatted()) \(unit)"
}

struct PlannerView: View {
    let hasPlan: Bool
    let showWeek: () -> Void
    let onGenerated: (MealPlan) -> Void

    @AppStorage("meal.server") private var server = "http://127.0.0.1:8000"
    @State private var budget = "8000"
    @FocusState private var editingBudget: Bool
    @State private var people = 4
    @State private var days = 3
    @State private var restrictions: Set<String> = []
    @State private var preferences: Set<String> = []
    @State private var error: String?
    @State private var loading = false

    private let dietary = [
        Choice(id: "no_beef", title: "No beef", icon: "fork.knife", color: MealPalette.terracotta),
        Choice(id: "no_chicken", title: "No chicken", icon: "bird", color: MealPalette.saffron),
        Choice(id: "vegetarian", title: "Vegetarian", icon: "leaf", color: MealPalette.olive),
        Choice(id: "no_eggs", title: "No eggs", icon: "oval", color: MealPalette.plum),
        Choice(id: "no_dairy", title: "No dairy", icon: "mug", color: MealPalette.saffron)
    ]
    private let priorities = [
        Choice(id: "traditional", title: "Traditional Pakistani meals", icon: "frying.pan", color: MealPalette.terracotta),
        Choice(id: "quick", title: "Quick meals (30 minutes or less)", icon: "bolt", color: MealPalette.saffron)
    ]

    var body: some View {
        NavigationStack {
            MealPage {
                hero
                budgetCard
                householdCard
                durationCard
                MealCard("Dietary restrictions", "Vegetarian includes eggs and dairy unless you exclude them.",
                     icon: "leaf", color: MealPalette.olive) {
                    choices(dietary, selection: $restrictions)
                }
                MealCard("What sounds good?", "Pick any preferences you’d like us to prioritize.",
                     icon: "sparkles", color: MealPalette.plum) {
                    choices(priorities, selection: $preferences)
                }
                Text("Sample prices include full grocery packs and pantry staples.")
                    .font(.footnote)
                    .foregroundStyle(MealPalette.secondaryText)
                if hasPlan {
                    Button(action: showWeek) {
                        Label("Open last meal plan", systemImage: "clock.arrow.circlepath")
                    }
                    .disabled(loading)
                }
                DisclosureGroup("Developer settings") {
                    TextField("Backend address", text: $server)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                        .padding(.top, 8)
                }
                .font(.footnote)
                .foregroundStyle(MealPalette.secondaryText)
                .accessibilityIdentifier("planner-developer-settings")
                Color.clear.frame(height: 12).accessibilityHidden(true)
            }
            .safeAreaInset(edge: .bottom, spacing: 0) {
                generateBar
            }
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle("Project Meal")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    private var hero: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 6) {
                Text("THE HOUSEHOLD TABLE")
                    .font(.caption2.bold())
                    .tracking(1.5)
                    .foregroundStyle(MealPalette.terracotta)
                Text("What’s cooking?")
                    .font(.largeTitle.bold())
                    .foregroundStyle(.primary)
                Text("Plan Pakistani lunches and dinners for the whole table.")
                    .font(.subheadline)
                    .foregroundStyle(MealPalette.secondaryText)
            }
            Spacer(minLength: 0)
            ZStack(alignment: .topTrailing) {
                Circle()
                    .fill(MealPalette.saffron.opacity(0.18))
                    .frame(width: 72, height: 72)
                    .overlay {
                        Image(systemName: "frying.pan.fill")
                            .font(.system(size: 28, weight: .semibold))
                            .foregroundStyle(MealPalette.terracotta)
                            .rotationEffect(.degrees(-14))
                    }
                Image(systemName: "sparkles")
                    .foregroundStyle(MealPalette.olive)
            }
            .accessibilityHidden(true)
        }
        .padding(.vertical, 8)
    }

    private var budgetCard: some View {
        MealCard("Grocery budget", "Your total budget for all the days in this plan.",
             icon: "wallet.bifold", color: MealPalette.terracotta) {
            HStack(spacing: 10) {
                Text("PKR").font(.subheadline.bold()).foregroundStyle(MealPalette.terracotta)
                TextField("Amount", text: $budget, prompt: Text("Amount").foregroundStyle(MealPalette.secondaryText))
                    .font(.title2.monospacedDigit().bold())
                    .foregroundStyle(.primary)
                    .keyboardType(.numberPad)
                    .focused($editingBudget)
                    .accessibilityLabel("Total grocery budget in PKR")
                    .accessibilityIdentifier("grocery-budget")
                if !budget.isEmpty {
                    Button {
                        budget = ""
                        editingBudget = true
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .frame(width: 44, height: 44)
                            .foregroundStyle(MealPalette.secondaryText)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Clear budget")
                    .accessibilityIdentifier("clear-budget")
                }
            }
            .padding(.leading, 12)
            .frame(minHeight: 48)
            .background(MealPalette.control, in: RoundedRectangle(cornerRadius: 12))
        }
    }

    private var householdCard: some View {
        MealCard("Who’s eating?", "We’ll scale recipes to the number of people at your table.",
             icon: "person.2", color: MealPalette.olive) {
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 5), count: 5), spacing: 5) {
                ForEach(1...10, id: \.self) { person in
                    Button {
                        people = person
                    } label: {
                        Image(systemName: person <= people ? "person.fill" : "person")
                            .font(.body.weight(.semibold))
                            .foregroundStyle(person <= people ? MealPalette.olive : MealPalette.secondaryText)
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .background(
                                person <= people ? MealPalette.olive.opacity(0.18) : MealPalette.control,
                                in: RoundedRectangle(cornerRadius: 8)
                            )
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(person == 1 ? "1 person" : "\(person) people")
                    .accessibilityAddTraits(person == people ? .isSelected : [])
                    .accessibilityIdentifier("household-\(person)")
                }
            }
            Text(people == 1 ? "1 person selected" : "\(people) people selected")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.primary)
        }
    }

    private var durationCard: some View {
        MealCard("How many days?", "Each day includes lunch and dinner.",
             icon: "calendar", color: MealPalette.saffron) {
            HStack(spacing: 8) {
                ForEach([3, 5, 7], id: \.self) { duration in
                    let selected = days == duration
                    Button {
                        days = duration
                    } label: {
                        VStack(spacing: 5) {
                            Image(systemName: selected ? "checkmark.circle.fill" : "calendar")
                                .foregroundStyle(MealPalette.saffron)
                            Text("\(duration) days").font(.subheadline.bold())
                                .foregroundStyle(.primary)
                        }
                        .frame(maxWidth: .infinity, minHeight: 64)
                        .background(selected ? MealPalette.saffron.opacity(0.2) : MealPalette.control,
                                    in: RoundedRectangle(cornerRadius: 12))
                        .overlay {
                            RoundedRectangle(cornerRadius: 12)
                                .strokeBorder(selected ? MealPalette.saffron : MealPalette.outline,
                                              lineWidth: selected ? 2 : 1)
                        }
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(duration) days")
                    .accessibilityAddTraits(selected ? .isSelected : [])
                    .accessibilityIdentifier("duration-\(duration)")
                }
            }
        }
    }

    private var generateBar: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let error {
                Label(error, systemImage: "exclamationmark.circle")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(MealPalette.terracotta)
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(MealPalette.card, in: RoundedRectangle(cornerRadius: 12))
            }
            Button {
                Task { await generate() }
            } label: {
                HStack(spacing: 8) {
                    if loading { ProgressView().tint(.white) }
                    else { Image(systemName: "sparkles") }
                    Text(loading ? "Planning meals…" : "Generate meal plan").bold()
                }
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity, minHeight: 54)
                .background(Color(red: 0.52, green: 0.23, blue: 0.15),
                            in: RoundedRectangle(cornerRadius: 15))
            }
            .buttonStyle(.plain)
            .disabled(loading)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .background(MealPalette.dock)
        .overlay(alignment: .top) { Divider() }
    }

    private func choices(_ options: [Choice], selection: Binding<Set<String>>) -> some View {
        ForEach(options) { option in
            let selected = selection.wrappedValue.contains(option.id)
            Button {
                if selected { selection.wrappedValue.remove(option.id) }
                else { selection.wrappedValue.insert(option.id) }
            } label: {
                HStack(spacing: 10) {
                    MealBadge(icon: option.icon, color: option.color)
                    Text(option.title)
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(.primary)
                        .multilineTextAlignment(.leading)
                    Spacer(minLength: 0)
                    Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                        .foregroundStyle(selected ? option.color : MealPalette.secondaryText)
                        .accessibilityHidden(true)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
                .background(selected ? option.color.opacity(0.16) : MealPalette.control,
                            in: RoundedRectangle(cornerRadius: 10))
                .overlay {
                    RoundedRectangle(cornerRadius: 10)
                        .strokeBorder(selected ? option.color : MealPalette.clear, lineWidth: 1)
                }
            }
            .buttonStyle(.plain)
            .accessibilityAddTraits(selected ? .isSelected : [])
            .accessibilityIdentifier("choice-\(option.id)")
        }
    }

    @MainActor
    private func generate() async {
        guard !loading else { return }
        editingBudget = false
        guard let value = Int(budget.trimmingCharacters(in: .whitespacesAndNewlines)),
              (1...1_000_000).contains(value) else {
            error = "Enter a whole-PKR budget between 1 and 1,000,000."
            return
        }
        error = nil
        loading = true
        defer { loading = false }
        let request = PlanRequest(budgetPkr: value, householdSize: people, days: days,
                                  restrictions: restrictions.sorted(), preferences: preferences.sorted())
        do {
            let generated = try await APIClient(server: server).generate(request)
            onGenerated(generated)
        } catch let failure as APIClient.Failure {
            error = failure.localizedDescription
        } catch {
            self.error = "The backend returned an unexpected response. Try again."
        }
    }
}

private struct PlanView: View {
    let plan: MealPlan

    private func mealSummary(_ batch: Batch) -> String {
        let time = "\(batch.servings) servings · \(batch.minutes) min"
        guard let cost = batch.costPaisa else { return time }
        return "\(time) · ~\(pkr((cost + 50) / 100)) used"
    }

    private func date(for day: Int) -> Date? {
        guard let start = plan.startsOn else { return nil }
        return Calendar.current.date(byAdding: .day, value: day - 1, to: start)
    }

    private func dayTitle(_ day: Int) -> String {
        guard let date = date(for: day) else { return "Day \(day)" }
        return date.formatted(.dateTime.weekday(.wide).month(.abbreviated).day())
    }

    var body: some View {
        ScrollViewReader { scroll in
            MealPage {
                MealCard("Meal calendar", "\(plan.request.days) planned days · Tap a day for meals",
                         icon: "calendar", color: MealPalette.saffron) {
                    HStack(alignment: .top, spacing: 4) {
                        ForEach(1...7, id: \.self) { day in
                            let planned = day <= plan.request.days
                            Button {
                                withAnimation { scroll.scrollTo(day, anchor: .top) }
                            } label: {
                                VStack(spacing: 4) {
                                    Text(date(for: day)?.formatted(.dateTime.weekday(.abbreviated)) ?? "Day")
                                        .font(.caption2)
                                        .lineLimit(1)
                                        .minimumScaleFactor(0.7)
                                    Text(date(for: day)?.formatted(.dateTime.day()) ?? String(day))
                                        .font(.subheadline.bold())
                                    Circle()
                                        .fill(planned ? MealPalette.saffron : MealPalette.clear)
                                        .frame(width: 5, height: 5)
                                }
                                .foregroundStyle(planned ? MealPalette.primaryText : MealPalette.secondaryText)
                                .frame(maxWidth: .infinity, minHeight: 56)
                                .background(planned ? MealPalette.saffron.opacity(0.18) : MealPalette.control,
                                            in: RoundedRectangle(cornerRadius: 8))
                            }
                            .buttonStyle(.plain)
                            .disabled(!planned)
                            .accessibilityLabel(dayTitle(day))
                            .accessibilityHint(planned ? "Shows this day’s meals" : "No meals planned")
                            .accessibilityIdentifier("calendar-day-\(day)")
                        }
                    }
                }
                MealCard("Estimated checkout", "Illustrative prices · full packages · \(plan.request.householdSize) people",
                         icon: "wallet.bifold", color: MealPalette.terracotta) {
                    Text(pkr(plan.shoppingList.totalCostPkr)).font(.largeTitle.bold())
                    LabeledContent("Budget", value: pkr(plan.request.budgetPkr))
                    HStack {
                        Text("Budget left")
                        Spacer()
                        Text(pkr(plan.remainingBudgetPkr)).bold().foregroundStyle(MealPalette.olive)
                    }
                    NavigationLink {
                        ShoppingView(shopping: plan.shoppingList)
                    } label: {
                        MealLinkLabel("Shopping list", icon: "basket")
                    }
                    .buttonStyle(.plain)
                }
                ForEach(1...plan.request.days, id: \.self) { day in
                    MealCard(dayTitle(day), icon: "fork.knife", color: MealPalette.olive) {
                        ForEach(plan.meals.filter { $0.day == day }) { meal in
                            NavigationLink {
                                RecipeView(batch: meal.batch)
                            } label: {
                                HStack(spacing: 10) {
                                    CatalogArtwork(kind: .recipe, id: meal.batch.id, category: meal.batch.category, size: 44)
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(meal.slot.capitalized).font(.caption.bold()).foregroundStyle(MealPalette.secondaryText)
                                        Text(meal.batch.name).font(.headline).foregroundStyle(.primary)
                                        Text(mealSummary(meal.batch))
                                            .font(.caption).foregroundStyle(MealPalette.secondaryText)
                                    }
                                    Spacer(minLength: 0)
                                    Image(systemName: "chevron.right")
                                        .font(.caption.bold())
                                        .foregroundStyle(MealPalette.terracotta)
                                        .accessibilityHidden(true)
                                }
                                .padding(10)
                                .background(MealPalette.control, in: RoundedRectangle(cornerRadius: 10))
                            }
                            .buttonStyle(.plain)
                            .accessibilityIdentifier("meal-\(meal.id)")
                        }
                    }
                    .id(day)
                }
            }
            .navigationTitle("Your meal plan")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}

private struct CatalogArtwork: View {
    enum Kind: String { case recipe, ingredient }

    let kind: Kind
    let id: String?
    let category: String
    var size: CGFloat = 52

    private var placeholder: (String, MealColor) {
        switch category {
        case "Vegetables", "Produce": ("leaf.fill", MealPalette.olive)
        case "Grains & pulses", "Lentils", "Pulses", "Rice": ("carrot.fill", MealPalette.saffron)
        case "Chicken", "Beef", "Meat & eggs", "Eggs": ("fork.knife", MealPalette.terracotta)
        case "Dairy", "Pantry": ("mug.fill", MealPalette.plum)
        default: (kind == .recipe ? "frying.pan.fill" : "basket.fill", MealPalette.terracotta)
        }
    }

    var body: some View {
        Group {
            if let id, let photo = UIImage(named: "\(kind.rawValue)-\(id)") {
                Image(uiImage: photo).resizable().scaledToFill()
            } else {
                Image(systemName: placeholder.0)
                    .font(.system(size: size * 0.38, weight: .semibold))
                    .foregroundStyle(placeholder.1)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(placeholder.1.opacity(0.16))
            }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: size * 0.22))
        .accessibilityHidden(true)
    }
}

private struct FavoriteButton: View {
    @AppStorage("meal.favorites") private var stored = Data()
    let key: String

    private var favorites: Set<String> {
        (try? JSONDecoder().decode(Set<String>.self, from: stored)) ?? []
    }

    var body: some View {
        let saved = favorites.contains(key)
        Button {
            var updated = favorites
            if saved { updated.remove(key) } else { updated.insert(key) }
            if let data = try? JSONEncoder().encode(updated) { stored = data }
        } label: {
            Label(saved ? "Remove from favorites" : "Add to favorites",
                  systemImage: saved ? "heart.fill" : "heart")
        }
        .accessibilityIdentifier("favorite-toggle")
    }
}

private struct BrowseView: View {
    var favoritesOnly = false

    private enum Catalog: String, CaseIterable, Identifiable {
        case recipes = "Recipes"
        case ingredients = "Ingredients"
        var id: Self { self }
    }

    @AppStorage("meal.favorites") private var storedFavorites = Data()
    @AppStorage("meal.server") private var server = "http://127.0.0.1:8000"
    @State private var selected = Catalog.recipes
    @State private var query = ""
    @State private var recipes: [CatalogRecipe] = []
    @State private var ingredients: [CatalogIngredient] = []
    @State private var loadedServer: String?
    @State private var loading = true
    @State private var error: String?

    private var terms: [String] {
        query.split(whereSeparator: \.isWhitespace).map(String.init)
    }

    private func matches(_ fields: [String]) -> Bool {
        let searchable = fields.joined(separator: " ")
        return terms.allSatisfy { searchable.localizedStandardContains($0) }
    }

    private var favoriteKeys: Set<String> {
        (try? JSONDecoder().decode(Set<String>.self, from: storedFavorites)) ?? []
    }

    private var visibleRecipes: [CatalogRecipe] {
        let saved = favoriteKeys
        return recipes.filter {
            (!favoritesOnly || saved.contains("recipe-\($0.id)")) &&
            matches([$0.name, $0.category, $0.id] + $0.ingredients.map(\.name))
        }
    }

    private var visibleIngredients: [CatalogIngredient] {
        let saved = favoriteKeys
        return ingredients.filter {
            (!favoritesOnly || saved.contains("ingredient-\($0.id)")) &&
            matches([$0.name, $0.category, $0.id])
        }
    }

    var body: some View {
        MealPage {
            Picker("Catalog", selection: $selected) {
                ForEach(Catalog.allCases) { catalog in
                    Text(catalog.rawValue).tag(catalog)
                }
            }
            .pickerStyle(.segmented)
            if loading {
                ProgressView("Loading catalog…")
                    .frame(maxWidth: .infinity)
                    .padding()
            } else if let error {
                MealCard("Couldn’t load the catalog", error, icon: "wifi.exclamationmark", color: MealPalette.terracotta) {
                    Button("Try again") { Task { await load() } }
                        .buttonStyle(.bordered)
                }
            } else if selected == .recipes {
                let results = visibleRecipes
                if results.isEmpty { emptyResults }
                ForEach(results) { recipe in
                    NavigationLink {
                        RecipeView(batch: recipe.batch)
                    } label: {
                        catalogRow(recipe.name, subtitle: "\(recipe.category) · \(recipe.minutes) min",
                                   kind: .recipe, id: recipe.id, category: recipe.category)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("catalog-recipe-\(recipe.id)")
                }
            } else {
                let results = visibleIngredients
                if results.isEmpty { emptyResults }
                ForEach(results) { ingredient in
                    NavigationLink {
                        ingredientDetail(ingredient)
                    } label: {
                        catalogRow(ingredient.name, subtitle: ingredient.category,
                                   kind: .ingredient, id: ingredient.id, category: ingredient.category)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("catalog-ingredient-\(ingredient.id)")
                }
            }
        }
        .navigationTitle(favoritesOnly ? "Favorites" : "Browse")
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always),
                    prompt: "Search recipes or ingredients")
        .task(id: server) {
            if loadedServer != server { await load() }
        }
        .refreshable { await load() }
    }

    @ViewBuilder private var emptyResults: some View {
        if favoritesOnly && terms.isEmpty {
            MealCard("No saved \(selected.rawValue.lowercased())", "Tap the heart on a recipe or ingredient in Browse to save it here.",
                     icon: "heart", color: MealPalette.plum) {
                EmptyView()
            }
        } else {
            MealCard("No matches", "Try a dish, ingredient, or category name.",
                     icon: "magnifyingglass", color: MealPalette.olive) {
                Button("Clear search") { query = "" }
                    .buttonStyle(.bordered)
            }
        }
    }

    private func catalogRow(_ name: String, subtitle: String, kind: CatalogArtwork.Kind,
                            id: String, category: String) -> some View {
        HStack(spacing: 12) {
            CatalogArtwork(kind: kind, id: id, category: category)
            VStack(alignment: .leading, spacing: 4) {
                Text(name).font(.headline).foregroundStyle(.primary)
                Text(subtitle).font(.subheadline).foregroundStyle(MealPalette.secondaryText)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right")
                .font(.caption.bold()).foregroundStyle(MealPalette.terracotta)
                .accessibilityHidden(true)
        }
        .padding(12)
        .background(MealPalette.card, in: RoundedRectangle(cornerRadius: 16))
    }

    private func ingredientDetail(_ ingredient: CatalogIngredient) -> some View {
        MealPage {
            MealCard(ingredient.name, ingredient.category, icon: "basket", color: MealPalette.olive) {
                CatalogArtwork(kind: .ingredient, id: ingredient.id, category: ingredient.category, size: 104)
                LabeledContent("Package size", value: amount(ingredient.packageQuantity, ingredient.unit))
                LabeledContent("Sample package price", value: pkr(ingredient.packagePricePkr))
                Text("Illustrative pricing from the prototype dataset.")
                    .font(.footnote).foregroundStyle(MealPalette.secondaryText)
            }
        }
        .navigationTitle("Ingredient")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                FavoriteButton(key: "ingredient-\(ingredient.id)")
            }
        }
    }

    @MainActor
    private func load() async {
        loading = true
        error = nil
        let client = APIClient(server: server)
        do {
            async let recipeResponse = client.recipes()
            async let ingredientResponse = client.ingredients()
            let (newRecipes, newIngredients) = try await (recipeResponse, ingredientResponse)
            try Task.checkCancellation()
            recipes = newRecipes
            ingredients = newIngredients
            loadedServer = client.server
        } catch is CancellationError {
            return
        } catch {
            self.error = error.localizedDescription
        }
        loading = false
    }
}

private struct RecipeView: View {
    let batch: Batch

    var body: some View {
        List {
            Section {
                CatalogArtwork(kind: .recipe, id: batch.id, category: batch.category, size: 104)
                Text(batch.name).font(.title2.bold())
                Text("Serves \(batch.servings) · \(batch.minutes) min cooking")
                if let cost = batch.costPaisa {
                    LabeledContent("Estimated ingredients used", value: pkr((cost + 50) / 100))
                }
            } footer: {
                if batch.costPaisa != nil {
                    Text("Uses illustrative per-unit prices. Whole packages are priced separately in the shopping list.")
                }
            }
            .mealRows()
            Section("Ingredients for this batch") {
                ForEach(batch.ingredients) { line in
                    LabeledContent(line.name, value: amount(line.quantity, line.unit))
                }
            }
            .mealRows()
            Section("Method") {
                ForEach(batch.instructions.indices, id: \.self) { index in
                    Text("\(index + 1). \(batch.instructions[index])")
                }
            }
            .mealRows()
        }
        .mealSurface()
        .navigationTitle("Recipe")
        .toolbar {
            if let id = batch.id {
                ToolbarItem(placement: .topBarTrailing) {
                    FavoriteButton(key: "recipe-\(id)")
                }
            }
        }
    }
}

private struct ShoppingView: View {
    let shopping: ShoppingList
    @AppStorage("meal.purchased") private var purchasedData = Data()

    private var groups: [String: [ShoppingItem]] {
        Dictionary(grouping: shopping.items, by: \.category)
    }

    private var purchased: [String: Set<String>] {
        (try? JSONDecoder().decode([String: Set<String>].self, from: purchasedData)) ?? [:]
    }

    var body: some View {
        List {
            Section {
                LabeledContent("Estimated basket", value: pkr(shopping.totalCostPkr)).font(.headline)
            } footer: {
                Text("Illustrative prices. Tap an ingredient to mark it purchased on this device.")
            }
            .mealRows()
            ForEach(groups.keys.sorted(), id: \.self) { category in
                Section(category) {
                    ForEach(groups[category] ?? []) { line in
                        let checked = purchased[shopping.planId, default: []].contains(line.id)
                        Button {
                            var updated = purchased
                            if checked {
                                updated[shopping.planId, default: []].remove(line.id)
                            } else {
                                updated[shopping.planId, default: []].insert(line.id)
                            }
                            if let data = try? JSONEncoder().encode(updated) { purchasedData = data }
                        } label: {
                            HStack(alignment: .top) {
                                Image(systemName: checked ? "checkmark.circle.fill" : "circle")
                                    .foregroundStyle(Color.accentColor)
                                CatalogArtwork(kind: .ingredient, id: line.id, category: line.category, size: 34)
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(line.name).font(.headline).strikethrough(checked)
                                    Text("Need \(amount(line.quantity, line.unit)) · Buy \(line.packages) × \(amount(line.packageQuantity, line.unit))")
                                        .font(.caption).foregroundStyle(MealPalette.secondaryText)
                                }
                                Spacer()
                                Text(pkr(line.costPkr)).font(.subheadline)
                            }
                            .foregroundStyle(.primary)
                        }
                        .accessibilityAddTraits(checked ? .isSelected : [])
                        .accessibilityIdentifier("shopping-item-\(line.id)")
                        .accessibilityValue(checked ? "Purchased" : "Not purchased")
                    }
                }
                .mealRows()
            }
        }
        .mealSurface()
        .navigationTitle("Shopping list")
    }
}
