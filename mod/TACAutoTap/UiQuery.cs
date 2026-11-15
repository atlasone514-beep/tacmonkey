// "list" and "click <text>" for TAC Auto Tap: find the pressable UI elements on screen by the
// text written on them, so scripts can say "press Hard Stage 5" instead of using pictures.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Il2CppInterop.Runtime;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

namespace TACAutoTap;

internal sealed class UiElement
{
    public GameObject Handler;   // the object that takes the press
    public string Path;
    public string Text;          // every label inside it, joined with " | "
    public Vector2 Center;       // Unity screen coords (origin bottom-left)
    public Rect Box;             // screen rect
    public bool OnTop;           // a press at Center really reaches this element
    public bool Interactable;
}

internal static class UiQuery
{
    private static readonly Regex Tags = new("<[^>]+>");

    /// Every visible element that takes presses (buttons, toggles, tappable panels...), top-most
    /// reachability included. Duplicates (several graphics on one button) are merged.
    public static List<UiElement> Collect()
    {
        var byHandler = new Dictionary<IntPtr, UiElement>();
        var es = EventSystem.current;

        void Add(GameObject handler, RectTransform rt, bool interactable)
        {
            if (handler == null || rt == null || !handler.activeInHierarchy) return;
            if (byHandler.ContainsKey(handler.Pointer)) return;
            if (!ScreenRect(rt, out var box)) return;
            if (box.width < 2 || box.height < 2) return;
            if (box.xMax < 0 || box.yMax < 0 || box.xMin > Screen.width || box.yMin > Screen.height) return;
            byHandler[handler.Pointer] = new UiElement
            {
                Handler = handler,
                Path = TapRunner.PathOfPublic(handler),
                Text = LabelOf(handler),
                Center = box.center,
                Box = box,
                Interactable = interactable,
            };
        }

        foreach (var s in Selectable.allSelectablesArray)
        {
            if (s == null || !s.isActiveAndEnabled) continue;
            Add(s.gameObject, s.GetComponent<RectTransform>(), s.IsInteractable());
        }

        // Custom tappable things that aren't Selectables (map nodes, list rows...)
        var graphics = UnityEngine.Object.FindObjectsByType(Il2CppType.Of<Graphic>(), FindObjectsSortMode.None);
        foreach (var o in graphics)
        {
            var g = o.TryCast<Graphic>();
            if (g == null || !g.isActiveAndEnabled || !g.raycastTarget) continue;
            var handler = ExecuteEvents.GetEventHandler<IPointerClickHandler>(g.gameObject)
                          ?? ExecuteEvents.GetEventHandler<IPointerDownHandler>(g.gameObject);
            if (handler == null) continue;
            Add(handler, handler.GetComponent<RectTransform>() ?? g.rectTransform, true);
        }

        // Which ones a press at their centre would really reach (not hidden under a popup)
        if (es != null)
        {
            var results = new Il2CppSystem.Collections.Generic.List<RaycastResult>();
            foreach (var e in byHandler.Values)
            {
                var ped = new PointerEventData(es) { position = e.Center };
                results.Clear();
                es.RaycastAll(ped, results);
                if (results.Count == 0) continue;
                var top = results[0].gameObject;
                var h = ExecuteEvents.GetEventHandler<IPointerDownHandler>(top)
                        ?? ExecuteEvents.GetEventHandler<IPointerClickHandler>(top);
                e.OnTop = h != null && h.Pointer == e.Handler.Pointer;
            }
        }

        // top-to-bottom, left-to-right like reading the screen
        return byHandler.Values.OrderByDescending(e => Math.Round(e.Center.y / 20)).ThenBy(e => e.Center.x).ToList();
    }

    public static string ListJson()
    {
        var sb = new StringBuilder("[");
        var first = true;
        foreach (var e in Collect())
        {
            if (!first) sb.Append(',');
            first = false;
            sb.Append("{\"text\":").Append(Json(e.Text))
              .Append(",\"path\":").Append(Json(e.Path))
              .Append(",\"x\":").Append(F(e.Center.x / Screen.width))
              .Append(",\"y\":").Append(F(1f - e.Center.y / Screen.height))
              .Append(",\"w\":").Append(F(e.Box.width / Screen.width))
              .Append(",\"h\":").Append(F(e.Box.height / Screen.height))
              .Append(",\"top\":").Append(e.OnTop ? "true" : "false")
              .Append(",\"on\":").Append(e.Interactable ? "true" : "false")
              .Append('}');
        }
        return sb.Append(']').ToString();
    }

    /// Press the element whose label contains `query` (case-insensitive). Prefers elements that
    /// are on top and interactable; "#N" picks the N-th match (1-based) in reading order.
    public static string Click(string query, Func<Vector2, bool, string> press)
    {
        int pick = 1;
        var m = Regex.Match(query, @"\s+#(\d+)$");
        if (m.Success)
        {
            pick = int.Parse(m.Groups[1].Value);
            query = query.Substring(0, m.Index);
        }
        query = query.Trim();
        var all = Collect();
        var hits = all.Where(e => e.Text.IndexOf(query, StringComparison.OrdinalIgnoreCase) >= 0
                                  || e.Path.EndsWith("/" + query, StringComparison.OrdinalIgnoreCase)).ToList();
        if (hits.Count == 0) return $"notfound '{query}'";
        var usable = hits.Where(e => e.OnTop && e.Interactable).ToList();
        if (usable.Count == 0)
            return $"blocked '{query}' is on screen but covered or disabled: {hits[0].Path}";
        if (pick > usable.Count) return $"notfound '{query}' #{pick} (only {usable.Count})";
        var target = usable[pick - 1];
        var reply = press(target.Center, true);
        return reply.StartsWith("ok") ? $"ok {target.Path} [{target.Text}]" : reply;
    }

    private static bool ScreenRect(RectTransform rt, out Rect box)
    {
        box = default;
        var canvas = rt.GetComponentInParent<Canvas>();
        if (canvas == null) return false;
        canvas = canvas.rootCanvas;
        var cam = canvas.renderMode == RenderMode.ScreenSpaceOverlay ? null : canvas.worldCamera;
        var corners = new Il2CppInterop.Runtime.InteropTypes.Arrays.Il2CppStructArray<Vector3>(4);
        rt.GetWorldCorners(corners);
        float minX = float.MaxValue, minY = float.MaxValue, maxX = float.MinValue, maxY = float.MinValue;
        for (int i = 0; i < 4; i++)
        {
            var p = RectTransformUtility.WorldToScreenPoint(cam, corners[i]);
            minX = Math.Min(minX, p.x); maxX = Math.Max(maxX, p.x);
            minY = Math.Min(minY, p.y); maxY = Math.Max(maxY, p.y);
        }
        box = Rect.MinMaxRect(minX, minY, maxX, maxY);
        return true;
    }

    private static string LabelOf(GameObject go)
    {
        var parts = new List<string>();
        foreach (var t in go.GetComponentsInChildren<Text>())
            if (t != null && t.isActiveAndEnabled) Keep(parts, t.text);
        foreach (var t in go.GetComponentsInChildren<TMPro.TMP_Text>())
            if (t != null && t.isActiveAndEnabled) Keep(parts, t.text);
        return string.Join(" | ", parts);
    }

    private static void Keep(List<string> parts, string s)
    {
        if (string.IsNullOrWhiteSpace(s)) return;
        s = Tags.Replace(s, "").Replace('\n', ' ').Replace('\r', ' ').Trim();
        while (s.Contains("  ")) s = s.Replace("  ", " ");
        if (s.Length > 0 && !parts.Contains(s)) parts.Add(s);
    }

    private static string F(float v) => v.ToString("0.0000", CultureInfo.InvariantCulture);

    private static string Json(string s)
    {
        var sb = new StringBuilder("\"");
        foreach (var c in s ?? "")
        {
            switch (c)
            {
                case '"': sb.Append("\\\""); break;
                case '\\': sb.Append("\\\\"); break;
                default:
                    if (c < 0x20) sb.Append(' ');
                    else sb.Append(c);
                    break;
            }
        }
        return sb.Append('"').ToString();
    }
}
