package telegram

import "encoding/json"

// Event is a normalized representation of a Telegram Update.
type Event struct {
	Type      string         `json:"type"`
	ChatID    int64          `json:"chat_id"`
	UserID    int64          `json:"user_id"`
	Username  string         `json:"username"`
	Text      string         `json:"text"`
	MessageID int64          `json:"message_id"`
	Raw       map[string]any `json:"raw"`
}

// ParseUpdate converts a Telegram Update into a normalized Event.
// Returns nil if the update cannot be mapped to a supported event type.
func ParseUpdate(u Update) *Event {
	// Serialize the raw update for the Raw field
	raw := updateToMap(u)

	switch {
	case u.Message != nil:
		msg := u.Message
		var userID int64
		var username string
		if msg.From != nil {
			userID = msg.From.ID
			username = msg.From.Username
		}
		return &Event{
			Type:      "message",
			ChatID:    msg.Chat.ID,
			UserID:    userID,
			Username:  username,
			Text:      msg.Text,
			MessageID: msg.MessageID,
			Raw:       raw,
		}

	case u.EditedMessage != nil:
		msg := u.EditedMessage
		var userID int64
		var username string
		if msg.From != nil {
			userID = msg.From.ID
			username = msg.From.Username
		}
		return &Event{
			Type:      "edited_message",
			ChatID:    msg.Chat.ID,
			UserID:    userID,
			Username:  username,
			Text:      msg.Text,
			MessageID: msg.MessageID,
			Raw:       raw,
		}

	case u.CallbackQuery != nil:
		cq := u.CallbackQuery
		var chatID, messageID int64
		if cq.Message != nil {
			chatID = cq.Message.Chat.ID
			messageID = cq.Message.MessageID
		}
		return &Event{
			Type:      "callback_query",
			ChatID:    chatID,
			UserID:    cq.From.ID,
			Username:  cq.From.Username,
			Text:      cq.Data,
			MessageID: messageID,
			Raw:       raw,
		}
	}

	return nil
}

// updateToMap converts an Update to a map[string]any for the Raw field.
func updateToMap(u Update) map[string]any {
	b, err := json.Marshal(u)
	if err != nil {
		return map[string]any{}
	}
	var m map[string]any
	_ = json.Unmarshal(b, &m)
	return m
}
