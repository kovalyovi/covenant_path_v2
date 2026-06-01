#if canImport(UIKit)
import SwiftUI

/// Full covenant-path detail for one member, laid out like LCR's "new member" record. Driven by
/// `member.details` (the rich subtree); when that's nil it falls back to the flat fields so the page
/// still renders. Faithful port of `person_detail_page.dart`.
struct PersonDetailView: View {
    let member: Member

    private var d: MemberDetails? { member.details }

    private var baptismLine: String? {
        if member.isInvestigator {
            let goal = member.baptismGoalDate ?? ""
            return goal.isEmpty ? nil : "Planned baptism \(goal)"
        } else {
            let b = member.baptismDate ?? ""
            return (b.isEmpty || b == "needs-profile-api") ? nil : "Baptized \(b)"
        }
    }

    private var memberSince: String? {
        d?.memberSince ?? member.membershipDuration
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                header
                // Our covenant-path milestones (data LCR's view lacks).
                SectionCard(title: "Covenant Path", systemImage: "timeline.selection") {
                    GoldenHourChips(member: member, highlightNext: true, labeled: true)
                }
                if let d {
                    richBody(d)
                } else {
                    flatFallback
                }
            }
            .padding(16)
            .frame(maxWidth: 1000)
            .frame(maxWidth: .infinity)
        }
        .navigationTitle(member.displayName)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if let uuid = member.personUUID, !uuid.isEmpty,
               let url = URL(string: "https://lcr.churchofjesuschrist.org/records/member-profile/\(uuid)?lang=eng") {
                ToolbarItem(placement: .topBarTrailing) {
                    Link(destination: url) { Image(systemName: "arrow.up.right.square") }
                        .accessibilityLabel("Open in LCR")
                }
            }
        }
    }

    // MARK: - header

    private var header: some View {
        HStack(spacing: 16) {
            PhotoAvatar(name: member.name, photoURL: member.photoURL, size: 60)
            VStack(alignment: .leading, spacing: 2) {
                Text(member.displayName).font(.title3.bold())
                if let u = member.unitName, !u.isEmpty { Text(u).font(.subheadline) }
                if let ms = memberSince, !ms.isEmpty { Text(ms).font(.subheadline) }
                if let line = baptismLine { Text(line).font(.caption) }
            }
            .foregroundStyle(Color(hex: 0x1A237E))   // on-primaryContainer-ish indigo
            Spacer(minLength: 0)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(hex: 0xC5CAE9).opacity(0.6), in: RoundedRectangle(cornerRadius: 16))
    }

    // MARK: - rich body (details present)

    @ViewBuilder
    private func richBody(_ d: MemberDetails) -> some View {
        SacramentSection(details: d)
        FriendsSection(details: d, recordedYes: member.friends == "Yes")
        ListTextSection(title: "Priesthood Ordination", symbol: "rosette",
                        lines: d.priesthoodOrdinations ?? [],
                        emptyText: "No priesthood ordination on record.")
        ListTextSection(title: "Calling", symbol: "person.text.rectangle",
                        lines: d.callings ?? [],
                        emptyText: "Not yet been given a calling.",
                        emptyIsAlert: true, recordedYes: member.calling == "Yes")
        ListTextSection(title: "Ministering Assignment", symbol: "hands.sparkles",
                        lines: d.ministeringAssignments ?? [],
                        emptyText: "Not yet received a ministering assignment.",
                        recordedYes: member.ministeringAssignment == "Yes")
        NamesSection(title: "Ministering Brothers & Sisters", symbol: "person.3",
                     names: (d.ministeringBrothers ?? []) + (d.ministeringSisters ?? []),
                     emptyText: "No ministers assigned.",
                     recordedYes: member.ministeringBrothersSisters == "Yes")
        TempleSection(details: d)
        PrinciplesSection(details: d)
        TogglesSection(title: "Self-Reliance Classes Completed", symbol: "graduationcap",
                       items: d.selfReliance ?? [])
        TagsSection(tags: d.tags ?? [])
    }

    // MARK: - flat fallback (pre-`details` rows)

    private var flatFallback: some View {
        let fields: [(String, String?)] = [
            ("Unit", member.unitName), ("Baptism date", member.baptismDate),
            ("Birth date", member.birthDate), ("Friends", member.friends),
            ("Aaronic Priesthood", member.aaronicPriesthood),
            ("Melchizedek Priesthood", member.melchizedekPriesthood),
            ("Calling", member.calling),
            ("Ministering brothers/sisters", member.ministeringBrothersSisters),
            ("Ministering assignment", member.ministeringAssignment),
            ("Temple recommend", member.templeRecommend),
            ("Patriarchal blessing", member.patriarchalBlessing),
            ("Living ordinance", member.livingOrdinance),
        ]
        return VStack(spacing: 0) {
            Divider().padding(.vertical, 8)
            ForEach(fields, id: \.0) { label, value in
                HStack {
                    Text(label)
                    Spacer()
                    Text(value ?? "—").fontWeight(.medium)
                }
                .padding(.vertical, 8)
                Divider()
            }
        }
    }
}

// MARK: - "recorded yes" fallback note

/// When a status field says "Yes" but the (flaky) detail endpoint returned no names, say so instead
/// of "Not yet" — the chip and the section would otherwise contradict each other. Wording matches
/// `_recordedYesNote` (it's a temporary LCR-side data gap, not specific to this person).
struct RecordedYesNote: View {
    var body: some View {
        HStack(alignment: .top, spacing: 6) {
            Image(systemName: "info.circle").font(.caption)
            Text("Recorded as yes — names are temporarily unavailable from LCR and will appear once "
                 + "its detail data loads on a future sync.")
                .font(.callout)
        }
        .foregroundStyle(Color(hex: 0xFF8F00))   // amber 800
    }
}

func mutedText(_ text: String) -> some View {
    Text(text).foregroundStyle(.secondary)
}
#endif
