package messaging

import (
	"encoding/json"
	"log"
	"time"
	zmq "github.com/pebbe/zmq4"
)

type MessageBroker struct {
	SignalSub         *zmq.Socket
	DecisionPub       *zmq.Socket
	StatePub          *zmq.Socket
	IncomingSignals   chan SignalMessage
}

func NewMessageBroker() (*MessageBroker, error) {
	broker := &MessageBroker{
		IncomingSignals: make(chan SignalMessage, 100),
	}

	// 1. SUB: Listen to Rust Signals
	sub, _ := zmq.NewSocket(zmq.SUB)
	sub.SetSubscribe("SIGNAL")
	sub.Connect("tcp://localhost:5555")
	broker.SignalSub = sub

	// 2. PUB: Broadcast Decisions to Python
	pubDec, _ := zmq.NewSocket(zmq.PUB)
	pubDec.Bind("tcp://*:5556")
	broker.DecisionPub = pubDec

	// 3. PUB: Broadcast State to Dashboard
	pubState, _ := zmq.NewSocket(zmq.PUB)
	pubState.Bind("tcp://*:5557")
	broker.StatePub = pubState

	log.Println("[IPC] ZeroMQ Message Broker initialized.")
	return broker, nil
}

func (b *MessageBroker) ListenForSignals() {
	poller := zmq.NewPoller()
	poller.Add(b.SignalSub, zmq.POLLIN)

	for {
		polled, _ := poller.Poll(100 * time.Millisecond)
		for _, item := range polled {
			msg, _ := item.Socket.RecvMessage(0)
			if len(msg) >= 2 && msg[0] == "SIGNAL" {
				var sig SignalMessage
				if json.Unmarshal([]byte(msg[1]), &sig) == nil {
					b.IncomingSignals <- sig
				}
			}
		}
	}
}

func (b *MessageBroker) PublishDecision(decision DecisionMessage) error {
	data, _ := json.Marshal(decision)
	_, err := b.DecisionPub.SendMessage("DECISION", string(data))
	return err
}

func (b *MessageBroker) PublishState(state StateMessage) error {
	data, _ := json.Marshal(state)
	_, err := b.StatePub.SendMessage("STATE", string(data))
	return err
}