// "items", "inspect" and "scroll" for TAC Auto Tap: read what a list (e.g. a quest's Loot row)
// contains straight from the game's objects - every entry, even ones scrolled out of view.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using Il2CppInterop.Runtime;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;
using BF = Il2CppSystem.Reflection.BindingFlags;

namespace TACAutoTap;

internal static class UiInspect
{
    private const BF Fields = BF.Instance | BF.Public | BF.NonPublic | BF.DeclaredOnly;

    /// Top-most raycast hit at a Unity screen position, or null.
    private static GameObject HitAt(Vector2 pos)
    {
        var es = EventSystem.current;
        if (es == null) return null;
        var results = new Il2CppSystem.Collections.Generic.List<RaycastResult>();
        es.RaycastAll(new PointerEventData(es) { position = pos }, results);
        return results.Count > 0 ? results[0].gameObject : null;
    }

    /// "items FX FY": the list (ScrollRect) under the point - one line per entry of its content.
    public static string Items(Vector2 pos)
    {
        var hit = HitAt(pos);
        if (hit == null) return "notfound nothing under the point";
        var sr = hit.GetComponentInParent<ScrollRect>();
        if (sr == null || sr.content == null) return $"notfound no list at {TapRunner.PathOfPublic(hit)}";
        return DescribeList(sr.content);
    }

    /// "itemsof PART": like "items", but finds the list by a piece of its path instead of by
    /// pointing at it - for screens with something over the list (a quest's results screen has
    /// a full-screen skip button above its drops).
    public static string ItemsOf(string part)
    {
        foreach (var o in UnityEngine.Object.FindObjectsOfType(Il2CppType.Of<ScrollRect>()))
        {
            var sr = o.TryCast<ScrollRect>();
            if (sr == null || !sr.isActiveAndEnabled || sr.content == null) continue;
            if (TapRunner.PathOfPublic(sr.content.gameObject).Contains(part) ||
                TapRunner.PathOfPublic(sr.gameObject).Contains(part))
                return DescribeList(sr.content);
        }
        return $"notfound no list matching {part}";
    }

    private static string DescribeList(Transform content)
    {
        var sb = new StringBuilder($"ok {TapRunner.PathOfPublic(content.gameObject)} entries={content.childCount}");
        for (int i = 0; i < content.childCount; i++)
        {
            var child = content.GetChild(i).gameObject;
            if (!child.activeSelf) continue;
            sb.Append(" ||| #").Append(i).Append(' ').Append(Describe(child, deep: true));
        }
        return sb.ToString();
    }

    /// "inspect FX FY": the object under the point and its parents.
    public static string Inspect(Vector2 pos)
    {
        var hit = HitAt(pos);
        if (hit == null) return "notfound nothing under the point";
        var sb = new StringBuilder("ok");
        var t = hit.transform;
        for (int up = 0; t != null && up < 4; up++, t = t.parent)
            sb.Append(" ||| ").Append(TapRunner.PathOfPublic(t.gameObject)).Append(" :: ").Append(Describe(t.gameObject, deep: up == 0));
        return sb.ToString();
    }

    /// "scroll FX FY V": move the list under the point; V = 0..1 (vertical: 1 top, 0 bottom;
    /// horizontal: 0 left, 1 right).
    public static string Scroll(Vector2 pos, float v)
    {
        var hit = HitAt(pos);
        if (hit == null) return "notfound nothing under the point";
        var sr = hit.GetComponentInParent<ScrollRect>();
        if (sr == null) return $"notfound no list at {TapRunner.PathOfPublic(hit)}";
        if (sr.vertical) sr.verticalNormalizedPosition = v;
        else sr.horizontalNormalizedPosition = v;
        return $"ok {TapRunner.PathOfPublic(sr.gameObject)} {(sr.vertical ? "vertical" : "horizontal")}={v}";
    }

    /// Components of an object (and with deep=true its children), with their simple field values,
    /// one level into plain data objects, plus the names of the pictures they show.
    private static string Describe(GameObject go, bool deep)
    {
        var parts = new List<string>();
        var objects = deep ? go.GetComponentsInChildren<Transform>(true).Select(x => x.gameObject).ToList()
                           : new List<GameObject> { go };
        var pictures = new List<string>();
        foreach (var o in objects)
        {
            foreach (var img in o.GetComponents<Image>())
                if (img != null && img.enabled && img.sprite != null) Add(pictures, img.sprite.name);
            foreach (var raw in o.GetComponents<RawImage>())
                if (raw != null && raw.enabled && raw.texture != null) Add(pictures, raw.texture.name);
            foreach (var txt in o.GetComponents<Text>())
                if (txt != null && txt.enabled && !string.IsNullOrWhiteSpace(txt.text)) Add(pictures, "text:" + txt.text.Replace('\n', ' '));
            foreach (var c in o.GetComponents<Component>())
            {
                if (c == null) continue;
                var type = c.GetIl2CppType();
                var ns = type.Namespace ?? "";
                if (ns.StartsWith("UnityEngine") || ns.StartsWith("TMPro")) continue;
                var fields = FieldValues(c.Cast<Il2CppSystem.Object>(), type, 2);
                if (fields.Length > 0) parts.Add($"{type.Name}{{{fields}}}");
            }
        }
        return (parts.Count > 0 ? string.Join(" ", parts) : "(no game components)")
               + (pictures.Count > 0 ? " pics=[" + string.Join(", ", pictures) + "]" : "");
    }

    private static string FieldValues(Il2CppSystem.Object obj, Il2CppSystem.Type type, int depth)
    {
        var parts = new List<string>();
        for (var t = type; t != null && parts.Count < 40; t = t.BaseType)
        {
            var full = t.FullName ?? "";
            if (full.StartsWith("UnityEngine.") || full == "System.Object") break;
            foreach (var f in t.GetFields(Fields))
            {
                try
                {
                    var ft = f.FieldType;
                    var fname = ft.FullName ?? "";
                    if (ft.IsPrimitive || ft.IsEnum || fname == "System.String")
                    {
                        var v = f.GetValue(obj);
                        if (v == null) continue;
                        var s = v.ToString();
                        if (string.IsNullOrEmpty(s) || s == "0" || s == "False") continue;
                        parts.Add($"{f.Name}={Short(s)}");
                    }
                    else if (depth > 1 && !ft.IsValueType && !fname.StartsWith("UnityEngine.")
                             && !fname.StartsWith("System.") && !fname.StartsWith("Il2CppSystem."))
                    {
                        var v = f.GetValue(obj);
                        if (v == null) continue;
                        var inner = FieldValues(v, v.GetIl2CppType(), depth - 1);
                        if (inner.Length > 0) parts.Add($"{f.Name}<{inner}>");
                    }
                }
                catch
                {
                    // some fields can't be read this way - skip them
                }
            }
        }
        return string.Join(",", parts);
    }

    private static void Add(List<string> list, string s)
    {
        if (!string.IsNullOrEmpty(s) && !list.Contains(s)) list.Add(Short(s));
    }

    private static string Short(string s) => s.Length > 80 ? s.Substring(0, 80) + "..." : s;
}
