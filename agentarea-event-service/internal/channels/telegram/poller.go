package telegram

import (
	"context"
	"fmt"

	"github.com/agentarea/event-service/internal/channels"
	"github.com/agentarea/event-service/internal/submit"
)

// Poller implements channels.ChannelPoller for Telegram Bot API.
type Poller struct {
	client *Client
	chatID int64 // filled from first message if not set
}

// NewPoller creates a Telegram poller from trigger config.
// Config must contain "bot_token".
func NewPoller(config map[string]any) channels.ChannelPoller {
	botToken, _ := config["bot_token"].(string)
	if botToken == "" {
		return nil
	}
	return &Poller{
		client: NewClient(botToken),
	}
}

func (p *Poller) Poll(ctx context.Context, offset int64) (*channels.PollResult, error) {
	updates, err := p.client.GetUpdates(ctx, offset)
	if err != nil {
		return nil, fmt.Errorf("telegram getUpdates: %w", err)
	}

	if len(updates) == 0 {
		return &channels.PollResult{}, nil
	}

	result := &channels.PollResult{}

	for _, upd := range updates {
		event := ParseUpdate(upd)
		if event == nil {
			result.NewOffset = upd.UpdateID + 1
			continue
		}

		result.Events = append(result.Events, submit.Event{
			Type:      event.Type,
			ChatID:    event.ChatID,
			UserID:    event.UserID,
			Username:  event.Username,
			Text:      event.Text,
			MessageID: event.MessageID,
			Raw:       event.Raw,
		})

		result.ChannelOrigin = map[string]any{
			"type":              "telegram",
			"chat_id":           fmt.Sprintf("%d", event.ChatID),
			"message_id":        event.MessageID,
			"user_display_name": event.Username,
			"presentation":      "concise",
		}

		result.NewOffset = upd.UpdateID + 1
	}

	return result, nil
}
