#if canImport(UIKit)
import SwiftUI

// The Person Detail page's individual sections, each a faithful port of the matching private widget
// in `person_detail_page.dart`. Sections that have no data render nothing (EmptyView), matching the
// Flutter `SizedBox.shrink()` early-returns.

// MARK: - Sacrament attendance dots

/// Newest-first stored list; shows the most recent 6 Sundays (rendered oldest→newest so the timeline
/// reads left-to-right) with a "View all" expander. Mirrors `_SacramentSection`.
struct SacramentSection: View {
    let details: MemberDetails
    @State private var expanded = false
    private let recent = 6

    private var all: [MemberDetails.SacramentEntry] { details.sacrament ?? [] }

    private var shown: [MemberDetails.SacramentEntry] {
        let slice = expanded ? all : Array(all.prefix(recent))
        return slice.reversed()
    }

    private var missed: Int {
        details.sacramentMissed ?? all.filter { $0.attended != true }.count
    }

    var body: some View {
        if all.isEmpty {
            EmptyView()
        } else {
            SectionCard(title: "Attended Sacrament Meeting", systemImage: "calendar.badge.checkmark",
                        trailing: all.count > recent ? AnyView(
                            Button(expanded ? "Show recent" : "View all (\(all.count))") {
                                expanded.toggle()
                            }.font(.caption)
                        ) : nil) {
                VStack(alignment: .leading, spacing: 10) {
                    FlowLayout(spacing: 14, lineSpacing: 10) {
                        ForEach(Array(shown.enumerated()), id: \.offset) { _, s in
                            VStack(spacing: 4) {
                                Text(s.label ?? "").font(.caption)
                                AttendanceDot(attended: s.attended == true)
                            }
                        }
                    }
                    if missed > 0 {
                        Text("\(missed) sacrament meeting\(missed == 1 ? "" : "s") missed")
                            .foregroundStyle(.red)
                    }
                }
            }
        }
    }
}

struct AttendanceDot: View {
    let attended: Bool
    var body: some View {
        let green = Color(hex: 0x388E3C)
        ZStack {
            Circle()
                .fill(attended ? green : .clear)
                .frame(width: 26, height: 26)
                .overlay(Circle().stroke(attended ? green : Color(hex: 0xBDBDBD), lineWidth: 1.4))
            if attended {
                Image(systemName: "checkmark").font(.system(size: 12, weight: .bold)).foregroundStyle(.white)
            }
        }
    }
}

// MARK: - Friends in the Church

struct FriendsSection: View {
    let details: MemberDetails
    let recordedYes: Bool
    private var friends: [MemberDetails.Friend] { details.friends ?? [] }

    var body: some View {
        SectionCard(title: "Friends in the Church", systemImage: "person.2") {
            if friends.isEmpty {
                if recordedYes { RecordedYesNote() } else { mutedText("No friends recorded yet.") }
            } else {
                VStack(alignment: .leading, spacing: 0) {
                    if friends.contains(where: { $0.inStake == true }) {
                        Text("Inside the Stake").font(.caption).padding(.bottom, 4)
                    }
                    ForEach(Array(friends.enumerated()), id: \.offset) { _, f in
                        HStack(spacing: 10) {
                            InitialsAvatar(name: f.name, size: 30)
                            VStack(alignment: .leading) {
                                Text(f.name ?? "—")
                                if let u = f.unit, !u.isEmpty { Text(u).font(.caption).foregroundStyle(.secondary) }
                            }
                            Spacer()
                        }
                        .padding(.vertical, 3)
                    }
                }
            }
        }
    }
}

// MARK: - simple text-line section (priesthood / calling / ministering assignment)

struct ListTextSection: View {
    let title: String
    let symbol: String
    let lines: [String]
    let emptyText: String
    var emptyIsAlert = false
    var recordedYes = false

    var body: some View {
        SectionCard(title: title, systemImage: symbol) {
            if lines.isEmpty {
                if recordedYes {
                    RecordedYesNote()
                } else {
                    Text(emptyText).foregroundStyle(emptyIsAlert ? .red : .secondary)
                }
            } else {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(Array(lines.enumerated()), id: \.offset) { _, l in
                        Text(l).padding(.vertical, 2)
                    }
                }
            }
        }
    }
}

// MARK: - names section (ministering brothers & sisters)

struct NamesSection: View {
    let title: String
    let symbol: String
    let names: [String]
    let emptyText: String
    var recordedYes = false

    var body: some View {
        SectionCard(title: title, systemImage: symbol) {
            if names.isEmpty {
                if recordedYes { RecordedYesNote() } else { mutedText(emptyText) }
            } else {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(names.enumerated()), id: \.offset) { _, n in
                        HStack(spacing: 10) {
                            InitialsAvatar(name: n, size: 28)
                            Text(n)
                            Spacer()
                        }
                        .padding(.vertical, 3)
                    }
                }
            }
        }
    }
}

// MARK: - Temple ordinances & experiences

struct TempleSection: View {
    let details: MemberDetails
    private var experiences: [MemberDetails.Toggle] { details.templeExperiences ?? [] }
    private var ordinances: [String] { details.templeOrdinances ?? [] }

    var body: some View {
        if experiences.isEmpty && ordinances.isEmpty {
            EmptyView()
        } else {
            SectionCard(title: "Temple Ordinances and Experiences", systemImage: "building.columns") {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(experiences.enumerated()), id: \.offset) { _, t in
                        ToggleRow(label: t.name ?? "", on: t.done == true)
                    }
                    if !ordinances.isEmpty { Spacer().frame(height: 8) }
                    ForEach(Array(ordinances.enumerated()), id: \.offset) { _, o in
                        Text(o).padding(.vertical, 2)
                    }
                }
            }
        }
    }
}

// MARK: - Principles Taught

struct PrinciplesSection: View {
    let details: MemberDetails
    private var lessons: [MemberDetails.Lesson] { details.lessons ?? [] }
    private let green = Color(hex: 0x388E3C)

    var body: some View {
        if lessons.isEmpty {
            EmptyView()
        } else {
            SectionCard(title: "Principles Taught", systemImage: "book",
                        trailing: AnyView(
                            HStack(spacing: 4) {
                                Image(systemName: "person.fill").font(.caption)
                                Text("= Member Present").font(.caption)
                            }.foregroundStyle(green))) {
                VStack(alignment: .leading, spacing: 12) {
                    ForEach(Array(lessons.enumerated()), id: \.offset) { _, l in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(l.name ?? "").foregroundStyle(green).fontWeight(.medium)
                            FlowLayout(spacing: 6) {
                                ForEach(Array((l.principles ?? []).enumerated()), id: \.offset) { _, p in
                                    PrincipleDot(taught: p.isTaught, memberPresent: p.memberPresent == true)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

struct PrincipleDot: View {
    let taught: Bool
    let memberPresent: Bool
    private let green = Color(hex: 0x388E3C)
    var body: some View {
        ZStack {
            Circle().fill(taught ? green : .clear)
                .frame(width: 22, height: 22)
                .overlay(Circle().stroke(green, lineWidth: 1.4))
            if memberPresent {
                Image(systemName: "person.fill").font(.system(size: 11))
                    .foregroundStyle(taught ? .white : green)
            }
        }
    }
}

// MARK: - toggle list (self-reliance) + a single toggle row

struct TogglesSection: View {
    let title: String
    let symbol: String
    let items: [MemberDetails.Toggle]

    var body: some View {
        if items.isEmpty {
            EmptyView()
        } else {
            SectionCard(title: title, systemImage: symbol) {
                VStack(spacing: 0) {
                    ForEach(Array(items.enumerated()), id: \.offset) { _, t in
                        ToggleRow(label: t.name ?? "", on: t.done == true)
                    }
                }
            }
        }
    }
}

struct ToggleRow: View {
    let label: String
    let on: Bool
    private let green = Color(hex: 0x388E3C)
    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: on ? "checkmark.circle.fill" : "circle")
                .foregroundStyle(on ? green : Color(hex: 0xBDBDBD))
            Text(label).fontWeight(on ? .medium : .regular)
            Spacer()
        }
        .padding(.horizontal, 12).padding(.vertical, 9)
        .background(on ? green.opacity(0.08) : Color(.tertiarySystemFill).opacity(0.4),
                    in: RoundedRectangle(cornerRadius: 10))
        .padding(.vertical, 3)
    }
}

// MARK: - Flags

struct TagsSection: View {
    let tags: [String]
    var body: some View {
        if tags.isEmpty {
            EmptyView()
        } else {
            SectionCard(title: "Flags", systemImage: "flag") {
                FlowLayout(spacing: 8) {
                    ForEach(Array(tags.enumerated()), id: \.offset) { _, t in
                        Text(t).font(.caption)
                            .padding(.horizontal, 10).padding(.vertical, 5)
                            .background(Color(hex: 0xFFECB3), in: Capsule())   // amber 100
                            .foregroundStyle(.primary)
                    }
                }
            }
        }
    }
}
#endif
