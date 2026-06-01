#if canImport(UIKit)
import SwiftUI

/// Row of milestone chips for one member — the iOS Golden Hour pattern this whole project echoes.
/// Filled = complete. With `highlightNext`, the first not-yet-complete milestone gets an amber ring
/// as the suggested next step. `labeled` switches between full-text pills (person detail) and
/// compact circles (lists). Faithful port of `GoldenHourChips`.
public struct GoldenHourChips: View {
    let member: Member
    let size: CGFloat
    let highlightNext: Bool
    let labeled: Bool

    public init(member: Member, size: CGFloat = 24, highlightNext: Bool = false, labeled: Bool = false) {
        self.member = member; self.size = size
        self.highlightNext = highlightNext; self.labeled = labeled
    }

    private var list: [Milestone] { Milestones.applicable(to: member) }
    private var nextIndex: Int? { highlightNext ? Milestones.nextStepIndex(for: member) : nil }

    public var body: some View {
        FlowLayout(spacing: labeled ? 8 : 5) {
            ForEach(Array(list.enumerated()), id: \.element.id) { idx, ms in
                let done = ms.complete(member)
                let isNext = idx == nextIndex
                if labeled {
                    labeledChip(ms, done: done, isNext: isNext)
                } else {
                    circleChip(ms, done: done, isNext: isNext)
                }
            }
        }
    }

    // Compact circle chip (lists).
    private func circleChip(_ ms: Milestone, done: Bool, isNext: Bool) -> some View {
        let border = done ? StatusColor.done : (isNext ? StatusColor.next : Color(hex: 0xBDBDBD))
        let fill = done ? StatusColor.done : (isNext ? StatusColor.next.opacity(0.15) : .clear)
        let textColor: Color = done ? .white : (isNext ? StatusColor.next : Color(hex: 0x757575))
        return Text(ms.abbr)
            .font(.system(size: ms.abbr.count >= 2 ? 8.5 : 11, weight: .bold))
            .foregroundStyle(textColor)
            .frame(width: size, height: size)
            .background(fill, in: Circle())
            .overlay(Circle().stroke(border, lineWidth: isNext ? 2 : 1.2))
            .accessibilityLabel("\(ms.label): \(done ? "done" : (isNext ? "next step" : "not yet"))")
    }

    // Full-text pill (person detail).
    private func labeledChip(_ ms: Milestone, done: Bool, isNext: Bool) -> some View {
        let c = done ? StatusColor.done : (isNext ? StatusColor.next : StatusColor.off)
        let symbol = done ? "checkmark.circle.fill" : (isNext ? "arrow.forward" : "circle")
        return HStack(spacing: 5) {
            Image(systemName: symbol).font(.system(size: 13))
            Text(ms.label).font(.system(size: 13, weight: .medium))
        }
        .foregroundStyle(c)
        .padding(.horizontal, 10).padding(.vertical, 5)
        .background((done || isNext) ? c.opacity(0.12) : .clear, in: Capsule())
        .overlay(Capsule().stroke(c, lineWidth: isNext ? 1.6 : 1))
    }
}
#endif
